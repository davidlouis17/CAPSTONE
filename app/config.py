from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

APP_NAME = os.getenv("APP_NAME", "Local Thrift")
APP_ENV = os.getenv("APP_ENV", "development")
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY", "local-thrift-dev-secret-key-ubah-di-produksi")

_raw_db_url = os.getenv("DATABASE_URL", "sqlite:///./local_thrift.db")
if _raw_db_url.startswith("sqlite:///"):
    _db_rel = _raw_db_url.replace("sqlite:///", "", 1)
    DATABASE_PATH = (BASE_DIR / _db_rel).resolve() if not Path(_db_rel).is_absolute() else Path(_db_rel)
else:
    DATABASE_PATH = (BASE_DIR / "local_thrift.db").resolve()

UPLOAD_DIR = (BASE_DIR / os.getenv("UPLOAD_DIR", "app/static/uploads")).resolve()
CNN_MODEL_PATH = (BASE_DIR / os.getenv("CNN_MODEL_PATH", "ml/models/shoe_condition_cnn.h5")).resolve()
