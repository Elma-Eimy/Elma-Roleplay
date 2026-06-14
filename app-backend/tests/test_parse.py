import os
import sys
# 将当前目录的父目录加入 python path 以确保能正确引入 services 和 core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.parse import parse_character_card

def test_parse_json_card(file_path:str):
    try:
        character_data = parse_character_card(file_path)
        print("Parsed Character Data (JSON):")
    except Exception as e:
        print(f"Error parsing JSON card: {e}")

if __name__ == "__main__":
    print("Testing JSON character card parsing...")
    test_parse_json_card(r"C:\Users\20752\Downloads\main_your-cold-crush-f50f64dc7d70_spec_v2.png")
