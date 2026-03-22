import os
import json
import random
import logging
from app.db.session import SessionLocal
from app.models.scam_number import ScamNumber, ScamType, RiskLevel

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

def seed_database():
    db = SessionLocal()
    try:
        existing_count = db.query(ScamNumber).count()
        if existing_count > 0:
            logger.warning(f"Database already has {existing_count} records. We will add new ones.")
            
        inserted_count: int = 0
        
        if not os.path.exists(GENDATA_DIR):
            logger.error(f"Cannot find the data directory at {GENDATA_DIR}")
            return
            
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
        
    except Exception as e:
        logger.error(f"Seeding failed: {str(e)}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    logger.info("Starting db seed...")
    seed_database()
    logger.info("Done!")
