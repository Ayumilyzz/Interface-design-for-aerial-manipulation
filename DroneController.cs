using UnityEngine;
using UnityEngine.InputSystem;

public class DroneController : MonoBehaviour
{
    [Header("Drone Settings")]
    [Range(0.5f, 5f)] public float droneSpeedMultiplier = 1f;
    [Range(0.5f, 5f)] public float rotateSpeedMultiplier = 1f;
    [Range(0.5f, 5f)] public float verticalSpeedMultiplier = 1f;

    public float moveSpeed = 1f;
    public float rotateSpeed = 30f;
    public float verticalSpeed = 1f;

    [Header("Arm Control Settings")]
    public Transform endEffector;
    public float armMoveSpeed = 1.5f;
    [Range(0.5f, 5f)] public float armSensitivityMultiplier = 3f;

    private Vector3 armLocalMin = new Vector3(-1.5f, 0.5f, -2f);
    private Vector3 armLocalMax = new Vector3(1.5f, 1.0f, 2f);

    private Vector2 moveInput;     // x=左右, y=前后
    private Vector2 upDownYaw;     // x=左右旋转, y=上下
    private Vector2 armXZInput;    // 手臂左右+前后
    private float armYInput;       // 手臂上下

    private DroneControls controls;

    private enum ControlMode { Drone, Arm }
    private ControlMode currentMode = ControlMode.Drone;
    public string ControlModeName => currentMode.ToString();

    // ========= 悬浮（来回漂 + 倾斜；无Yaw噪声） =========
    [Header("Hover Oscillation (来回漂)")]
    [Tooltip("基础左右漂移半径（米），作为强度=1时的幅度")]
    public float baseXAmplitude = 0.9f;
    [Tooltip("基础前后漂移半径（米），作为强度=1时的幅度")]
    public float baseZAmplitude = 0.5f;

    [Tooltip("左右完整来回周期（秒）（固定，不随滑杆变化）")]
    public float xPeriod = 4.0f;
    [Tooltip("前后完整来回周期（秒）（固定，不随滑杆变化）")]
    public float zPeriod = 5.5f;

    [Tooltip("上下轻微呼吸感（米）")]
    public float microBobAmplitude = 0.01f;

    [Header("Hover Strength Sliders（运行时可调）")]
    [Range(0f, 1f)] public float lateralHoverStrength = 1f;   // 左右 0~1
    [Range(0f, 1f)] public float forwardHoverStrength = 0.6f; // 前后 0~1

    [Header("Subtle Variations）")]
    [Range(0f, 0.5f)] public float phaseJitter = 0.12f;
    [Range(0f, 0.5f)] public float periodJitter = 0.1f;
    public float jitterSpeed = 0.07f;

    [Header("Tilt（根据漂移“速度”映射到倾斜）")]
    public float maxRollDeg = 12f;   // 左右更“晃”
    public float maxPitchDeg = 7f;
    public float tiltFollowSpeed = 6f;

    [Header("Mode Multipliers")]
    public float normalAmplitudeMul = 1f;
    public float armModeAmplitudeMul = 0.35f;

    [Header("Hover Toggle (Gamepad A / Space)")]
    public bool hoverEnabled = true;       // 当前是否生效
    public bool logHoverToggle = true;

    // ====== 组合式姿态（玩家 + 悬浮）======
    private Vector3 userLocalPos;
    private Quaternion userLocalRot;

    private Vector3 noiseOffset = Vector3.zero;
    private Quaternion noiseRot = Quaternion.identity;

    // 倾斜内部
    private float currentPitch; // 绕X（前后点头）
    private float currentRoll;  // 绕Z（左右倾斜）

    // 相位随机种子
    private float xPhaseSeed;
    private float zPhaseSeed;

    // 输入动作：切换悬浮
    private InputAction toggleHoverAction;

    // ==== Hover Tuning（新增：可运行时平滑调幅度&周期） ====
    [Header("Hover Tuning (runtime adjustable)")]
    [Tooltip("参数平滑追随速度（越大过渡越快）")]
    public float hoverParamLerpSpeed = 3f;

    // 运行时目标值（API 改它们）
    private float targetBaseXAmplitude;
    private float targetBaseZAmplitude;
    private float targetXPeriod;
    private float targetZPeriod;

    // 运行时当前值（用于实际计算，平滑过渡）
    private float curBaseXAmplitude;
    private float curBaseZAmplitude;
    private float curXPeriod;
    private float curZPeriod;

    private void Awake()
    {
        controls = new DroneControls();

        // 🎮 水平移动
        controls.Drone.ForwardBackwardLeftRight.performed += ctx => moveInput = ctx.ReadValue<Vector2>();
        controls.Drone.ForwardBackwardLeftRight.canceled  += _  => moveInput = Vector2.zero;

        // 🎮 上下 + 左右旋转
        controls.Drone.UpDownRotate.performed += ctx => upDownYaw = ctx.ReadValue<Vector2>();
        controls.Drone.UpDownRotate.canceled  += _  => upDownYaw = Vector2.zero;

        // 🤖 手臂
        controls.Drone.MoveArmHorizontalForwardBackward.performed += ctx => armXZInput = ctx.ReadValue<Vector2>();
        controls.Drone.MoveArmHorizontalForwardBackward.canceled  += _  => armXZInput = Vector2.zero;

        controls.Drone.MoveArmUpDown.performed += ctx => armYInput = ctx.ReadValue<float>();
        controls.Drone.MoveArmUpDown.canceled  += _  => armYInput = 0f;

        // 🔁 模式切换
        controls.Drone.ToggleArmControl.performed += _ =>
        {
            currentMode = (currentMode == ControlMode.Drone) ? ControlMode.Arm : ControlMode.Drone;
            Debug.Log("🎮 控制模式切换为: " + currentMode);
        };

        // 🔘 切换悬浮（Gamepad A / Keyboard Space）
        toggleHoverAction = new InputAction("ToggleHover", InputActionType.Button);
        toggleHoverAction.AddBinding("<Gamepad>/buttonSouth"); // A
        toggleHoverAction.AddBinding("<Keyboard>/space");
        toggleHoverAction.performed += _ =>
        {
            hoverEnabled = !hoverEnabled;
            if (logHoverToggle) Debug.Log($"Hover {(hoverEnabled ? "ENABLED" : "DISABLED")}");
        };
    }

    private void OnEnable()
    {
        controls?.Enable();
        toggleHoverAction?.Enable();
    }

    private void OnDisable()
    {
        toggleHoverAction?.Disable();
        controls?.Disable();
    }

    private void Start()
    {
        userLocalPos = transform.localPosition;
        userLocalRot = transform.localRotation;

        // 随机相位种子，让每次运行略有不同
        xPhaseSeed = Random.Range(0f, 1000f);
        zPhaseSeed = Random.Range(0f, 1000f);

        // 初始化 hover 目标/当前值为 Inspector 的初始设置（新增）
        targetBaseXAmplitude = curBaseXAmplitude = baseXAmplitude;
        targetBaseZAmplitude = curBaseZAmplitude = baseZAmplitude;
        targetXPeriod        = curXPeriod        = xPeriod;
        targetZPeriod        = curZPeriod        = zPeriod;
    }

    private void Update()
    {
        // 1) 更新悬浮（来回漂 + 倾斜）
        UpdateHoverOscillation();

        // 2) 玩家输入：更新基座
        if (currentMode == ControlMode.Drone) UpdateUserFromInput();
        else MoveArmEndEffector();

        // 3) 合成最终姿态
        transform.localPosition = userLocalPos + noiseOffset;
        transform.localRotation = userLocalRot * noiseRot;
    }

    private void UpdateUserFromInput()
    {
        float dt = Time.deltaTime;

        // 平面移动（相对玩家朝向）
        Vector3 localMove = new Vector3(moveInput.x, 0f, moveInput.y) *
                            (moveSpeed * droneSpeedMultiplier * dt);
        userLocalPos += userLocalRot * localMove;

        // 垂直
        userLocalPos.y += upDownYaw.y * verticalSpeed * verticalSpeedMultiplier * dt;

        // 玩家主动Yaw旋转（噪声层不添加Yaw）
        float yawDeg = upDownYaw.x * rotateSpeed * rotateSpeedMultiplier * dt;
        if (Mathf.Abs(yawDeg) > 0f)
            userLocalRot = Quaternion.AngleAxis(yawDeg, Vector3.up) * userLocalRot;
    }

    private void UpdateHoverOscillation()
    {
        float dt = Time.deltaTime;
        float t  = Time.time;

        // —— 平滑追随目标参数（让调整不会突兀）——（新增）
        float k = Mathf.Clamp01(hoverParamLerpSpeed * dt);
        curBaseXAmplitude = Mathf.Lerp(curBaseXAmplitude, targetBaseXAmplitude, k);
        curBaseZAmplitude = Mathf.Lerp(curBaseZAmplitude, targetBaseZAmplitude, k);
        curXPeriod        = Mathf.Lerp(curXPeriod,        targetXPeriod,        k);
        curZPeriod        = Mathf.Lerp(curZPeriod,        targetZPeriod,        k);

        // 手臂模式降低幅度，避免干扰
        float ampMulMode = (currentMode == ControlMode.Arm) ? armModeAmplitudeMul : normalAmplitudeMul;

        // 如果悬浮关闭，则把噪声清零
        if (!hoverEnabled)
        {
            noiseOffset = Vector3.zero;
            // 平滑把倾斜收回
            currentRoll  = Mathf.Lerp(currentRoll,  0f, Mathf.Clamp01(tiltFollowSpeed * dt));
            currentPitch = Mathf.Lerp(currentPitch, 0f, Mathf.Clamp01(tiltFollowSpeed * dt));
            noiseRot = Quaternion.Euler(currentPitch, 0f, currentRoll);
            return;
        }

        // —— 极慢的相位/周期抖动（让“左-右-左-右”不那么机械）——
        float jitterT = t * jitterSpeed;
        float xPhaseOff = (Mathf.PerlinNoise(xPhaseSeed, jitterT) - 0.5f) * 2f * phaseJitter * Mathf.PI; // 弧度
        float zPhaseOff = (Mathf.PerlinNoise(zPhaseSeed, jitterT) - 0.5f) * 2f * phaseJitter * Mathf.PI;

        float xPeriodMul = 1f + (Mathf.PerlinNoise(jitterT, xPhaseSeed) - 0.5f) * 2f * periodJitter;
        float zPeriodMul = 1f + (Mathf.PerlinNoise(jitterT + 33.3f, zPhaseSeed) - 0.5f) * 2f * periodJitter;

        float xW = Mathf.PI * 2f / Mathf.Max(0.0001f, curXPeriod * xPeriodMul); // 改：用 curXPeriod
        float zW = Mathf.PI * 2f / Mathf.Max(0.0001f, curZPeriod * zPeriodMul); // 改：用 curZPeriod

        // —— 最终幅度 = 基础幅度 * 强度滑杆 * 模式倍率 —— 
        float xAmp = curBaseXAmplitude * Mathf.Clamp01(lateralHoverStrength) * ampMulMode; // 改：用 curBaseXAmplitude
        float zAmp = curBaseZAmplitude * Mathf.Clamp01(forwardHoverStrength) * ampMulMode; // 改：用 curBaseZAmplitude

        // —— 来回漂：正弦位移（米）——
        float x = Mathf.Sin(t * xW + xPhaseOff) * xAmp; // 左 ↔ 右
        float z = Mathf.Sin(t * zW + zPhaseOff) * zAmp; // 前 ↔ 后

        // 上下轻微呼吸
        float y = (microBobAmplitude > 0f)
            ? (Mathf.PerlinNoise(t * 0.35f, 0f) - 0.5f) * 2f * microBobAmplitude
            : 0f;

        // —— 速度（m/s）：用于映射倾斜角 —— d/dt(sin)=cos * ω
        float vx = Mathf.Cos(t * xW + xPhaseOff) * xW * xAmp;
        float vz = Mathf.Cos(t * zW + zPhaseOff) * zW * zAmp;

        // 归一化映射到角度
        float vxRef = Mathf.Max(0.0001f, xAmp * xW);
        float vzRef = Mathf.Max(0.0001f, zAmp * zW);
        float targetRoll  = Mathf.Clamp(-vx / vxRef, -1f, 1f) * maxRollDeg;  // 右移速度→右倾
        float targetPitch = Mathf.Clamp( vz / vzRef, -1f, 1f) * maxPitchDeg; // 前进速度→低头

        currentRoll  = Mathf.Lerp(currentRoll,  targetRoll,  Mathf.Clamp01(tiltFollowSpeed * dt));
        currentPitch = Mathf.Lerp(currentPitch, targetPitch, Mathf.Clamp01(tiltFollowSpeed * dt));

        noiseOffset = new Vector3(x, y, z);
        noiseRot    = Quaternion.Euler(currentPitch, 0f, currentRoll); // 无Yaw
    }

    private void MoveArmEndEffector()
    {
        if (endEffector == null) return;

        float effectiveSpeed = armMoveSpeed * armSensitivityMultiplier;

        Vector3 delta = new Vector3(armXZInput.x, armYInput, armXZInput.y);
        Vector3 newLocalPos = endEffector.localPosition + delta * effectiveSpeed * Time.deltaTime;

        newLocalPos.x = Mathf.Clamp(newLocalPos.x, armLocalMin.x, armLocalMax.x);
        newLocalPos.y = Mathf.Clamp(newLocalPos.y, armLocalMin.y, armLocalMax.y);
        newLocalPos.z = Mathf.Clamp(newLocalPos.z, armLocalMin.z, armLocalMax.z);

        endEffector.localPosition = newLocalPos;
    }

    // ======= 公开 API（新增） =======

    /// <summary>直接设置漂移幅度（米）。</summary>
    public void SetHoverAmplitude(float xAmplitude, float zAmplitude)
    {
        targetBaseXAmplitude = Mathf.Max(0f, xAmplitude);
        targetBaseZAmplitude = Mathf.Max(0f, zAmplitude);
    }

    /// <summary>直接设置周期（秒）。</summary>
    public void SetHoverPeriod(float xPeriodSec, float zPeriodSec)
    {
        targetXPeriod = Mathf.Max(0.0001f, xPeriodSec);
        targetZPeriod = Mathf.Max(0.0001f, zPeriodSec);
    }
}
