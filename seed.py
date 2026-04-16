import os
import json
import random
import logging
from app.db.session import SessionLocal
from app.models.scam_number import ScamNumber, ScamType, RiskLevel
from app.models.user import User, GenderType
from app.models.device import Device
from app.models.scam_report import ScamReport

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path to exactly what we investigated
GENDATA_DIR = os.path.join(os.getcwd(), 'data_scam_repo', 'gendata')

def map_scam_type(folder_name):
    folder_name = folder_name.lower()
    if 'đầu tư' in folder_name:
        return ScamType.INVESTMENT
    if 'vay' in folder_name:
        return ScamType.LOAN
    if 'tuyển' in folder_name or 'tuyển dụng' in folder_name:
        return ScamType.RECRUITMENT
    if 'giả' in folder_name or 'mạo danh' in folder_name:
        return ScamType.IMPERSONATION
    return ScamType.OTHER

def seed_users(db, count=20):
    logger.info(f"Seeding {count} random users...")
    first_names = ["Nguyen", "Tran", "Le", "Pham", "Hoang", "Huynh", "Phan", "Vu", "Dang", "Bui"]
    last_names = ["An", "Binh", "Chinh", "Dung", "Em", "Giang", "Hung", "Khanh", "Linh", "Minh"]
    
    users_created = 0
    for i in range(count):
        phone = f"+849{random.randint(100, 999)}{random.randint(1000, 9999)}"
        if not db.query(User).filter(User.phone == phone).first():
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            user = User(
                phone=phone,
                fullName=name,
                email=f"{name.lower().replace(' ', '.')}@example.com",
                gender=random.choice([GenderType.MALE, GenderType.FEMALE, GenderType.OTHER]),
                is_verified=True
            )
            db.add(user)
            users_created += 1
            
    db.commit()
    logger.info(f"Successfully seeded {users_created} users!")

def seed_from_translate(db, sample_size=150):
    logger.info(f"Seeding up to {sample_size} records from translate dataset...")
    translate_path = os.path.join(os.getcwd(), 'data_scam_repo', 'translate', 'tele28k_scam_translate.json')
    inserted_count = 0
    
    if os.path.exists(translate_path):
        try:
            with open(translate_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            samples = random.sample(data, min(sample_size, len(data)))
            
            for index, item in enumerate(samples):
                phone = f"+84999{random.randint(100, 999)}{random.randint(10, 99)}"
                scam_type = random.choice([ScamType.INVESTMENT, ScamType.LOAN, ScamType.RECRUITMENT, ScamType.IMPERSONATION])
                risk_level = random.choice([RiskLevel.HIGH, RiskLevel.CRITICAL])
                
                if not db.query(ScamNumber).filter(ScamNumber.phone == phone).first():
                    metadata_info = {
                        "source": "tele28k",
                        "summary": item.get("result", "N/A")[0:255], # Cap length to avoid huge DB
                        "analysis_excerpt": item.get("thinking", "N/A")[0:255]
                    }
                    
                    new_scam = ScamNumber(
                        phone=phone,
                        scam_type=scam_type,
                        risk_level=risk_level,
                        reportCount=random.randint(10, 100),
                        is_verified=True,
                        is_ai_vetted=True,
                        metadata_info=metadata_info
                    )
                    db.add(new_scam)
                    inserted_count += 1
            
            db.commit()
            logger.info(f"Successfully seeded {inserted_count} translate records!")
        except Exception as e:
            logger.error(f"Error seeding from translate: {e}")
    else:
        logger.warning(f"Translate data file not found at {translate_path}")

def seed_database():
    db = SessionLocal()
    try:
        # 1. Seed Scam Numbers
        existing_count = db.query(ScamNumber).count()
        if existing_count > 0:
            logger.warning(f"Database already has {existing_count} scam records. We will add new ones.")
            
        inserted_count: int = 0
        
        if not os.path.exists(GENDATA_DIR):
            logger.error(f"Cannot find the data directory at {GENDATA_DIR}")
        else:
            folders = [f for f in os.listdir(GENDATA_DIR) if os.path.isdir(os.path.join(GENDATA_DIR, f))]
            
            for folder_idx, folder_name in enumerate(folders, start=1):
                category_path = os.path.join(GENDATA_DIR, folder_name)
                core_json_path = os.path.join(category_path, 'core.json')
                
                if os.path.exists(core_json_path):
                    try:
                        with open(core_json_path, 'r', encoding='utf-8') as f:
                            scenarios = json.load(f)
                            
                        schema_scam_type = map_scam_type(folder_name)
                        
                        for scenario in scenarios:
                            scenario_id = scenario.get('_id', random.randint(1000, 9999))
                            phone = f"+849{folder_idx:02d}{scenario_id:05d}"
                            
                            if not db.query(ScamNumber).filter(ScamNumber.phone == phone).first():
                                risk_level = random.choice([RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL])
                                report_count = random.randint(1, 50)
                                
                                new_scam = ScamNumber(
                                    phone=phone,
                                    scam_type=schema_scam_type,
                                    risk_level=risk_level,
                                    reportCount=report_count,
                                    is_verified=True,
                                    metadata_info={"original_category": folder_name}
                                )
                                db.add(new_scam)
                                inserted_count += 1
                    except Exception as e:
                        logger.error(f"Error reading {core_json_path}: {e}")
                else:
                    logger.warning(f"No core.json found in {category_path}")
                    
            db.commit()
            logger.info(f"Successfully inserted {inserted_count} seed records!")
        
        # 1.5 Seed more from Translate Dataset
        seed_from_translate(db, sample_size=150)
        
        # 2. Seed Users
        seed_users(db, count=20)
        
    except Exception as e:
        logger.error(f"Seeding failed: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("Starting db seed...")
    seed_database()
    logger.info("Done!")
