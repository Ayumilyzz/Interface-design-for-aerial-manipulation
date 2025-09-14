// DroneYRandomizer.cs
using UnityEngine;
using UnityEngine.SceneManagement; // ⬅ 新增

[DisallowMultipleComponent]
public class DroneYRandomizer : MonoBehaviour
{
    [Header("要随机高度的对象（无人机根或相机）")]
    public Transform target;

    [Header("Y 高度范围")]
    public float minY = 10f;
    public float maxY = 25f;

    [Header("起始/手动随机")]
    public bool randomizeOnStart = true;

    void OnEnable()
    {
        // 每次场景加载完成后也随机一次（包括你按 X 重置后）
        SceneManager.sceneLoaded += OnSceneLoaded;
    }

    void OnDisable()
    {
        SceneManager.sceneLoaded -= OnSceneLoaded;
    }

    private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
    {
        ApplyRandomY();
    }

    void Start()
    {
        if (randomizeOnStart) ApplyRandomY();
    }

    [ContextMenu("Apply Random Y Now")]
    public void ApplyRandomY()
    {
        if (target == null) target = transform;
        var p = target.position;
        p.y = Random.Range(minY, maxY);
        target.position = p;
    }
}
