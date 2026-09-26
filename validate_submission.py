import json

def validate():
    valid_ctas = {"binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "open_ended", "none"}
    valid_send_as = {"vera", "merchant_on_behalf"}
    
    with open("submission.jsonl") as f:
        lines = f.read().splitlines()
        
    assert len(lines) == 30, f"Expected 30 lines, got {len(lines)}"
    
    for i, line in enumerate(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            print(f"Line {i+1} is not valid JSON")
            return
            
        required_keys = {"test_id", "body", "cta", "send_as", "suppression_key", "rationale"}
        assert set(data.keys()) == required_keys, f"Line {i+1} keys mismatch. Got {data.keys()}"
        
        assert data["cta"] in valid_ctas, f"Line {i+1} invalid cta: {data['cta']}"
        assert data["send_as"] in valid_send_as, f"Line {i+1} invalid send_as: {data['send_as']}"
        assert isinstance(data["body"], str) and len(data["body"]) > 0
        assert isinstance(data["suppression_key"], str)
        assert isinstance(data["rationale"], str) and len(data["rationale"]) > 0
        
    print("Validation passed! All 30 lines are strictly compliant.")

if __name__ == '__main__':
    validate()
