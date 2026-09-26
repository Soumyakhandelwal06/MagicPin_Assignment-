import json
from pathlib import Path
from composer import compose

def main():
    ds_dir = Path("expanded_dataset")
    out_file = Path("submission.jsonl")
    
    with open(ds_dir / "test_pairs.json") as fp:
        pairs = json.load(fp)["pairs"]
        
    lines = []
    for p in pairs:
        tid = p["test_id"]
        mid = p["merchant_id"]
        cid = p["customer_id"]
        trg_id = p["trigger_id"]
        
        with open(ds_dir / "merchants" / f"{mid}.json") as fp:
            merchant = json.load(fp)
            
        cat_slug = merchant["category_slug"]
        with open(ds_dir / "categories" / f"{cat_slug}.json") as fp:
            category = json.load(fp)
            
        with open(ds_dir / "triggers" / f"{trg_id}.json") as fp:
            trigger = json.load(fp)
            
        customer = None
        if cid:
            with open(ds_dir / "customers" / f"{cid}.json") as fp:
                customer = json.load(fp)
                
        composed = compose(category, merchant, trigger, customer)
        
        line = {
            "test_id": tid,
            "body": composed["body"],
            "cta": composed["cta"],
            "send_as": composed["send_as"],
            "suppression_key": composed["suppression_key"],
            "rationale": composed["rationale"]
        }
        lines.append(json.dumps(line))
        
    with open(out_file, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
        
    print(f"Generated {len(lines)} lines to {out_file}")

if __name__ == "__main__":
    main()
