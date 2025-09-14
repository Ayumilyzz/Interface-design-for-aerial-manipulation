using UnityEngine;

[DisallowMultipleComponent]
[DefaultExecutionOrder(10000)]
public class EndEffectorNoPenetration : MonoBehaviour
{
    [Header("对象引用（请务必设置）")]
    public Transform droneRoot;
    public Transform tip;

    [Header("几何与图层")]
    public float radius = 0.15f;
    public LayerMask wallMask = ~0;
    public bool includeTriggersAsWalls = false;

    [Header("命中过滤")]
    [Range(0f, 1f)] public float faceAlignDotThreshold = 0.5f;

    [Header("释放滞回")]
    public float releaseHysteresis = 0.01f;

    [Header("稳健性")]
    public int   binarySearchIters   = 18;
    public float binarySearchEpsilon = 0.0005f;
    public float microEpsilon        = 0.001f;

    [Header("调试")]
    public bool debugDraw = false;

    public bool IsContacting { get; private set; }
    public int  BumpCount    { get; private set; }

    Vector3 _lastSafeTip, _lastSafeRoot;
    bool    _initialized = false, _wasContacting = false;
    float   _releaseProgress = Mathf.Infinity;
    Vector3 _lastContactNormal = Vector3.zero;
    Collider[] _overlapCache = new Collider[16];

    void Reset(){ if (tip == null) tip = transform; }
    void Awake(){ if (tip == null) tip = transform; }

    void LateUpdate()
    {
        if (droneRoot == null || tip == null) return;

        Vector3 up = tip.up;
        Vector3 back = -up;

        if (!_initialized)
        {
            Vector3 root = droneRoot.position;
            for (int i = 0; i < 80; i++)
            {
                if (!OverlapsAt(tip.position)) break;
                root += back * microEpsilon;
                droneRoot.position = root;
            }
            _lastSafeTip  = tip.position;
            _lastSafeRoot = droneRoot.position;
            _initialized = true;
            IsContacting = false;
            _wasContacting = false;
            _releaseProgress = Mathf.Infinity;
            _lastContactNormal = Vector3.zero;
            return;
        }

        Vector3 desiredRoot = droneRoot.position;
        Vector3 desiredTip  = tip.position;

        Vector3 tipDelta = desiredTip - _lastSafeTip;
        float   tipDist  = tipDelta.magnitude;

        if (tipDist <= 1e-6f)
        {
            MaintainStickState();
            droneRoot.position = _lastSafeRoot;
            return;
        }

        Vector3 tipDir = tipDelta / Mathf.Max(tipDist, 1e-7f);

        bool hit = SphereCastFrontFiltered(_lastSafeTip, tipDir, tipDist, up, out RaycastHit h);

        Vector3 clampedTip = desiredTip;
        bool contactingThisFrame = false;
        Vector3 contactNormal = _lastContactNormal;

        if (hit)
        {
            // 命中处即为“首次接触”的球心位置（不前拉吸附）
            clampedTip = _lastSafeTip + tipDir * Mathf.Max(0f, h.distance);
            contactingThisFrame = true;
            contactNormal = h.normal;
        }
        else
        {
            if (OverlapsAt(desiredTip))
            {
                clampedTip = FindBoundaryByBisection(_lastSafeTip, desiredTip);
                contactingThisFrame = true;
                contactNormal = -up;
            }
        }

        if (contactingThisFrame)
        {
            Vector3 correction = clampedTip - desiredTip;
            Vector3 newRoot = desiredRoot + correction;
            droneRoot.position = newRoot;

            IsContacting = true;
            if (!_wasContacting && _releaseProgress >= releaseHysteresis)
                BumpCount++;
            _wasContacting = true;
            _releaseProgress = 0f;
            _lastContactNormal = contactNormal;

            if (debugDraw)
            {
                Debug.DrawLine(_lastSafeTip, clampedTip, Color.yellow);
                Debug.DrawRay(clampedTip, contactNormal * 0.2f, Color.red);
            }

            _lastSafeTip  = tip.position;
            _lastSafeRoot = droneRoot.position;
            return;
        }

        // 已贴墙：屏蔽朝墙分量，允许后退/切向
        if (_wasContacting)
        {
            Vector3 n = (_lastContactNormal != Vector3.zero) ? _lastContactNormal.normalized : -up;

            float forward = Vector3.Dot(tipDelta, -n);
            if (forward > 0f)
            {
                droneRoot.position = _lastSafeRoot; // 禁止继续朝墙推进
            }
            else
            {
                Vector3 tangential = Vector3.ProjectOnPlane(tipDelta, n);
                Vector3 allowedTip = _lastSafeTip + tangential;
                Vector3 correction  = allowedTip - desiredTip;
                droneRoot.position  = desiredRoot + correction;

                float backComp = Vector3.Dot(tipDelta, n); // >0 离墙
                if (backComp > 0f) _releaseProgress += backComp;
            }

            if (_releaseProgress >= releaseHysteresis)
            {
                IsContacting = false;
                _wasContacting = false;
                _lastContactNormal = Vector3.zero;
            }
            else
            {
                IsContacting = true;
            }

            if (debugDraw)
                Debug.DrawLine(_lastSafeTip, tip.position, Color.cyan);

            _lastSafeTip  = tip.position;
            _lastSafeRoot = droneRoot.position;
            return;
        }

        _lastSafeTip  = desiredTip;
        _lastSafeRoot = desiredRoot;
    }

    bool SphereCastFrontFiltered(Vector3 origin, Vector3 dir, float maxDist, Vector3 up, out RaycastHit best)
    {
        best = default;
        if (maxDist <= 1e-6f) return false;

        var hits = Physics.SphereCastAll(
            origin, radius, dir, maxDist,
            wallMask,
            includeTriggersAsWalls ? QueryTriggerInteraction.Collide : QueryTriggerInteraction.Ignore
        );
        if (hits == null || hits.Length == 0) return false;

        float bestD = float.PositiveInfinity;
        bool found = false;
        for (int i = 0; i < hits.Length; i++)
        {
            var h = hits[i];
            float align = Vector3.Dot(h.normal, up); // 正对期望 ≈ -1
            if (align <= -faceAlignDotThreshold)
            {
                if (h.distance < bestD)
                {
                    bestD = h.distance;
                    best = h;
                    found = true;
                }
            }
        }
        return found;
    }

    Vector3 FindBoundaryByBisection(Vector3 from, Vector3 to)
    {
        float lo = 0f, hi = 1f;
        for (int i = 0; i < binarySearchIters; i++)
        {
            float mid = (lo + hi) * 0.5f;
            Vector3 p = Vector3.Lerp(from, to, mid);
            if (OverlapsAt(p)) hi = mid; else lo = mid;
            if ((hi - lo) * Vector3.Distance(from, to) < binarySearchEpsilon) break;
        }
        return Vector3.Lerp(from, to, lo);
    }

    bool OverlapsAt(Vector3 tipPos)
    {
        int n = Physics.OverlapSphereNonAlloc(
            tipPos, radius,
            _overlapCache,
            wallMask,
            includeTriggersAsWalls ? QueryTriggerInteraction.Collide : QueryTriggerInteraction.Ignore
        );
        return n > 0;
    }

    void MaintainStickState()
    {
        if (_wasContacting)
        {
            _releaseProgress += Time.deltaTime * 0.001f;
            if (_releaseProgress >= releaseHysteresis)
            {
                IsContacting = false;
                _wasContacting = false;
                _lastContactNormal = Vector3.zero;
            }
            else
            {
                IsContacting = true;
            }
        }
    }

    void OnDrawGizmosSelected()
    {
        if (!debugDraw) return;
        var t = (tip != null) ? tip : transform;
        Gizmos.color = Color.green;
        Gizmos.DrawWireSphere(t.position, radius);
        Gizmos.color = Color.cyan;
        Gizmos.DrawRay(t.position, t.up * 0.25f);
    }
}
