from research_agent.platform.workers import VolumeMount, WorkerImagePolicy


def test_evaluate_worker_image_passes_a_clean_image() -> None:
    policy = WorkerImagePolicy()
    violations = policy.evaluate(
        image_paths=(
            "/app/src/research_agent/tools/client.py",
            "/app/.venv/bin/python",
        ),
        mounts=(),
        environment=("PATH=/usr/bin",),
    )
    assert violations == ()


def test_evaluate_worker_image_flags_a_model_cache_path() -> None:
    policy = WorkerImagePolicy()
    violations = policy.evaluate(
        image_paths=("/root/.cache/huggingface/hub/model.bin",),
        mounts=(),
        environment=(),
    )
    assert violations == ("image_path:/root/.cache/huggingface/hub/model.bin",)


def test_evaluate_worker_image_flags_a_model_volume_mount() -> None:
    policy = WorkerImagePolicy()
    violations = policy.evaluate(
        image_paths=(),
        mounts=(
            VolumeMount(destination="/var/lib/research-agent/models", read_only=True),
        ),
        environment=(),
    )
    assert violations == ("mount:/var/lib/research-agent/models",)


def test_evaluate_worker_image_flags_a_writable_hugging_face_cache_env() -> None:
    policy = WorkerImagePolicy()
    violations = policy.evaluate(
        image_paths=(),
        mounts=(),
        environment=("HF_HOME=/scratch/hf",),
    )
    assert violations == ("environment:HF_HOME",)


def test_evaluate_worker_image_reports_every_violation_at_once() -> None:
    policy = WorkerImagePolicy()
    violations = policy.evaluate(
        image_paths=("/app/models/head.bin",),
        mounts=(VolumeMount(destination="/var/run/docker.sock", read_only=True),),
        environment=("TRANSFORMERS_CACHE=/scratch",),
    )
    assert set(violations) == {
        "image_path:/app/models/head.bin",
        "mount:/var/run/docker.sock",
        "environment:TRANSFORMERS_CACHE",
    }
