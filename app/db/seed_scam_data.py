import sys
import os
import httpx
import random
from typing import List

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(project_root)

from app.db.session import SessionLocal
from app.models.scam_number import ScamNumber, ScamType, RiskLevel
from app.models.scam_report import ScamReport
from app.services.utils import normalize_phone

DATA_URL = "https://raw.githubusercontent.com/hoangvt2501/data_scam/main/localization/tele28k_scam.json"

def generate_vn_phone():
    prefixes = ["09", "08", "03", "07", "05"]
    prefix = random.choice(prefixes)
    suffix = "".join([str(random.randint(0, 9)) for _ in range(8)])
    return prefix + suffix

def map_scam_type(label_name: str) -> ScamType:
    try:
        label_name = label_name.lower()
        if "đầu tư" in label_name:
            return ScamType.INVESTMENT
        if "vay vốn" in label_name:
            return ScamType.LOAN
        if "tuyển dụng" in label_name or "trúng tuyển" in label_name:
            return ScamType.RECRUITMENT
        if any(x in label_name for x in ["giả danh", "mạo danh", "công an", "thuế", "ngân hàng"]):
            return ScamType.IMPERSONATION
        return ScamType.OTHER
    except Exception:
        return ScamType.OTHER

def seed_data(limit: int = 100):
    db = SessionLocal()
    try:
        print(f"🚀 Fetching dataset from: {DATA_URL}")
        with httpx.Client(timeout=30.0) as client:
            response = client.get(DATA_URL)
            response.raise_for_status()
            data = response.json()

        print(f"✅ Downloaded {len(data)} samples from dataset.")

        random.shuffle(data)
        samples = data[:limit]

        print("🧹 Clearing existing scam data...")
        db.query(ScamReport).delete()
        db.query(ScamNumber).delete()
        db.commit()

        count = 0
        for item in samples:
            raw_phone = generate_vn_phone()
            phone = normalize_phone(raw_phone)
            label_name = item.get("label_name", "Unknown")
            scam_type = map_scam_type(label_name)

            existing = db.query(ScamNumber).filter(ScamNumber.phone == phone).first()
            if existing:
                continue

            scam_number = ScamNumber(
                phone=phone,
                scam_type=scam_type,
                risk_level=RiskLevel.HIGH if random.random() > 0.3 else RiskLevel.CRITICAL,
                reportCount=random.randint(10, 100),
            )
            db.add(scam_number)
            db.add(ScamReport(phone=phone))

            count += 1
            if count % 20 == 0:
                print(f"📦 Seeded {count} records...")

        db.commit()
        print(f"✨ Seeding completed! Added {count} fraudulent numbers to database.")

    except httpx.HTTPError as he:
        print(f"❌ Network error: {he}")
    except Exception as e:
        print(f"❌ Error seeding data: {e}")
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    seed_limit = 100
    if len(sys.argv) > 1:
        try:
            seed_limit = int(sys.argv[1])
        except ValueError:
            pass

    seed_data(seed_limit)
