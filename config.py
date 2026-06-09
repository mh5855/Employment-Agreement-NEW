import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # 병원 정보
    HOSPITAL_NAME: str = field(default_factory=lambda: os.getenv("HOSPITAL_NAME", "좋은문화병원"))
    HOSPITAL_REPRESENTATIVE: str = field(default_factory=lambda: os.getenv("HOSPITAL_REPRESENTATIVE", "병원장"))
    HOSPITAL_ADDRESS: str = field(default_factory=lambda: os.getenv("HOSPITAL_ADDRESS", ""))
    HOSPITAL_BIZ_REG: str = field(default_factory=lambda: os.getenv("HOSPITAL_BIZ_REG", ""))

    # 이메일 설정
    EMAIL_HOST: str = field(default_factory=lambda: os.getenv("EMAIL_HOST", "smtp.gmail.com"))
    EMAIL_PORT: int = field(default_factory=lambda: int(os.getenv("EMAIL_PORT", "587")))
    EMAIL_USER: str = field(default_factory=lambda: os.getenv("EMAIL_USER", ""))
    EMAIL_PASSWORD: str = field(default_factory=lambda: os.getenv("EMAIL_PASSWORD", ""))
    EMAIL_FROM_NAME: str = field(default_factory=lambda: os.getenv("EMAIL_FROM_NAME", "좋은문화병원 인사총무팀"))
    ADMIN_EMAIL: str = field(default_factory=lambda: os.getenv("ADMIN_EMAIL", ""))
    SENDGRID_API_KEY: str = field(default_factory=lambda: os.getenv("SENDGRID_API_KEY", ""))

    # 전자서명
    ESIGN_PROVIDER: str = field(default_factory=lambda: os.getenv("ESIGN_PROVIDER", "modusign"))
    MODUSIGN_API_KEY: str = field(default_factory=lambda: os.getenv("MODUSIGN_API_KEY", ""))
    MODUSIGN_API_URL: str = "https://api.modusign.co.kr"
    MODUSIGN_WEBHOOK_SECRET: str = field(default_factory=lambda: os.getenv("MODUSIGN_WEBHOOK_SECRET", ""))

    # Google Drive
    GDRIVE_CREDENTIALS_FILE: str = field(default_factory=lambda: os.getenv("GDRIVE_CREDENTIALS_FILE", "credentials.json"))
    GDRIVE_ROOT_FOLDER_ID: str = field(default_factory=lambda: os.getenv("GDRIVE_ROOT_FOLDER_ID", ""))

    # 경로
    OUTPUT_DIR: str = field(default_factory=lambda: os.getenv("OUTPUT_DIR", "output"))
    DATA_DIR: str = field(default_factory=lambda: os.getenv("DATA_DIR", "data"))
    DB_PATH: str = field(default_factory=lambda: os.getenv("DB_PATH", "email_log.db"))
    ADMIN_PASSWORD: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", "admin1234"))

    # 서명 앱 URL (app.py 자체가 ?token= 파라미터로 서명 처리하므로 메인 앱과 동일 URL)
    SIGN_APP_URL: str = field(default_factory=lambda: os.getenv("SIGN_APP_URL", "http://localhost:8501"))

    def __post_init__(self):
        os.makedirs(self.OUTPUT_DIR, exist_ok=True)
        os.makedirs(self.DATA_DIR, exist_ok=True)


config = Config()
