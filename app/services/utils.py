import re

def normalize_phone(phone: str) -> str:
    """
    Chuẩn hóa số điện thoại:
    - Loại bỏ dấu cách, dấu ngoặc, dấu gạch ngang.
    - Chuyển đầu số 0 thành +84 (mặc định Việt Nam).
    """
    # Loại bỏ ký tự không phải số
    digits = re.sub(r'\D', '', phone)
    
    if digits.startswith('0'):
        return '+84' + digits[1:]
    if digits.startswith('84') and len(digits) > 9:
        return '+' + digits
    if not digits.startswith('84') and len(digits) <= 10:
         return '+84' + digits
         
    return '+' + digits
