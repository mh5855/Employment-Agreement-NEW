"""테스트 이메일 발송 스크립트."""
import sys, os
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv()

from config import config
from modules.data_loader import load_employees, load_salary_table, find_salary, compute_salary_summary
from modules.pdf_generator import generate_contract_pdf
from modules.pdf_encryptor import encrypt_pdf
from modules.email_sender import send_sign_request
from modules.web_signer import create_signing_token, build_sign_url
from modules.db_logger import log_email_sent

EMP_FILE    = os.path.join(config.DATA_DIR, "employees.xlsx")
SALARY_FILE = os.path.join(config.DATA_DIR, "salary_table.xlsx")

# 직원 로드
emps = load_employees(EMP_FILE)
emp = emps.iloc[0].to_dict()
emp["이메일"] = "mh0431@goodhospital.or.kr"

# 급여 정보
salary_table = load_salary_table(SALARY_FILE)
salary = find_salary(salary_table, emp["소속부서"], emp["직급"], emp["연차"])
summary = compute_salary_summary(salary) if salary else {}

# PDF 생성
raw = os.path.join(config.OUTPUT_DIR, f"{emp['사번']}_{emp['성명']}_근로계약서_원본.pdf")
generate_contract_pdf(emp, summary, raw)
print(f"PDF 생성: {raw}")

# 암호화 (주민번호 뒷 7자리 사용)
ssn = str(emp.get("주민등록번호", ""))
password = ssn.replace("-", "")[-7:] if ssn else "1234567"
enc = raw.replace("_원본.pdf", ".pdf")
encrypt_pdf(raw, enc, password)
print(f"암호화 완료: {enc}")
print(f"비밀번호: {password}")

# 서명 토큰 생성
token = create_signing_token(emp, enc)
sign_url = build_sign_url(token)
print(f"서명 URL: {sign_url}")

# 이메일 발송
send_sign_request(emp, enc, sign_url)
log_email_sent(emp, os.path.basename(enc))
print("이메일 발송 완료!")
