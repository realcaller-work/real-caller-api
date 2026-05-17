import json
import os
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer, TrainingArguments
from torch.utils.data import Dataset
import pyvi

class ScamDataset(Dataset):
    def __init__(self, texts, labels, tokenizer, max_length=256):
        self.encodings = tokenizer(texts, truncation=True, padding=True, max_length=max_length)
        self.labels = labels

    def __getitem__(self, idx):
        item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
        item['labels'] = torch.tensor(self.labels[idx])
        return item

    def __len__(self):
        return len(self.labels)

import os
import sys

# Add project root to path for DB imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.session import SessionLocal
from app.models.scam_report import ScamReport
from app.models.scam_number import ScamNumber

def load_data_from_db():
    print("💎 Loading real reports from PostgreSQL...")
    db = SessionLocal()
    # Only train from reports that are confirmed scams (or all reports if you want)
    reports = db.query(ScamReport).all()
    
    db_texts = []
    db_labels = []
    
    for r in reports:
        # Construct context from dialogue if exists, otherwise use description
        content = r.description
        if r.messages and isinstance(r.messages, list):
            dialogue = " ".join([m.get('content', '') for m in r.messages if isinstance(m, dict) and m.get('content')])
            if dialogue:
                content = dialogue
        
        if content and len(content.strip()) > 10:
            db_texts.append(content)
            db_labels.append(1) # Assuming reports are scams for now
            
    db.close()
    return db_texts, db_labels

def load_data(repo_path, sample_size=1000):
    print("📂 Loading seed dataset from JSON files...")
    texts = []
    labels = []
    
    # 1. Load from DB (Priority: Fresh user data)
    db_texts, db_labels = load_data_from_db()
    texts.extend(db_texts)
    labels.extend(db_labels)
    print(f"✅ Added {len(db_texts)} training samples from Database.")
    
    # 2. Load from JSON files (Repository data)
    # Load scam data
    scam_path = os.path.join(repo_path, 'translate', 'tele28k_scam_translate.json')
    if os.path.exists(scam_path):
        with open(scam_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data[:sample_size]:
                dialogue = " ".join([d.get('content', '') for d in item.get('dialogue', [])])
                if dialogue:
                    texts.append(dialogue)
                    labels.append(1)
                    
    # Load harmless data
    harmless_path = os.path.join(repo_path, 'translate', 'tele28k_harmless_translate.json')
    if os.path.exists(harmless_path):
        with open(harmless_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data[:sample_size]:
                dialogue = " ".join([d.get('content', '') for d in item.get('dialogue', [])])
                if dialogue:
                    texts.append(dialogue)
                    labels.append(0)
                    
    return texts, labels

def train():
    repo_path = "data_scam_repo"
    model_name = "vinai/phobert-base"
    output_dir = "./phobert_scam_model"
    
    texts, labels = load_data(repo_path, sample_size=50) # Very small sample for demonstration
    if not texts:
        print("No data found!")
        return

    print(f"Loaded {len(texts)} samples.")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)
    
    dataset = ScamDataset(texts, labels, tokenizer)
    
    # Split train/val (90/10)
    train_size = int(0.9 * len(dataset))
    val_size = len(dataset) - train_size
    train_dataset, val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])

    training_args = TrainingArguments(
        output_dir='./results',
        num_train_epochs=1,              # 1 epoch for quick demo
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        warmup_steps=10,
        weight_decay=0.01,
        logging_dir='./logs',
        logging_steps=10,
        use_cpu=not torch.cuda.is_available()
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset
    )

    print("Starting training...")
    trainer.train()
    
    print(f"Saving model to {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print("Training complete!")

if __name__ == "__main__":
    train()
