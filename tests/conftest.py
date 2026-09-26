import os
import tempfile

os.environ["LUCKY_DB"] = os.path.join(tempfile.mkdtemp(prefix="lucky-test-"), "lucky.db")
