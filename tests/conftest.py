import atexit
import os
import tempfile

# 测试环境隔离：app.main 消费的四个环境变量全部钉死，避免开发 shell 里
# 导出过任何一个（如 LUCKY_ADMIN_TOKEN/LUCKY_PRIZES_JSON/LUCKY_INVENTORY）
# 让 pytest 行为漂移甚至打到外部库存系统
_tmp = tempfile.mkdtemp(prefix="lucky-test-")
os.environ["LUCKY_DB"] = os.path.join(_tmp, "lucky.db")
os.environ["LUCKY_ADMIN_TOKEN"] = "123456"
os.environ.pop("LUCKY_PRIZES_JSON", None)
os.environ.pop("LUCKY_INVENTORY", None)


@atexit.register
def _cleanup_tmp_db():
    import shutil

    shutil.rmtree(_tmp, ignore_errors=True)
