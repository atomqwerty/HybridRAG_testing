from router import get_route
import sys

queries = [
    ("เบอร์ติดต่อคืออะไร", "fast_fact"),
    ("ออฟฟิศอยู่ที่ไหน", "fast_fact"),
    ("ในตารางหน้า 3 บอกว่าอะไร", "visual_layout"),
    ("กราฟนี้แสดงอะไร", "visual_layout"),
    ("วิเคราะห์ความเสี่ยง", "deep_reasoning"),
    ("ทำไมถึงเป็นแบบนั้น", "deep_reasoning"),
    ("Hello World", "fast_fact") # Default
]

print("🔍 Testing Thai Router...")
failed = 0
for q, expected in queries:
    route = get_route(q)
    status = "✅" if route == expected else f"❌ (Expected {expected})"
    print(f"[{status}] Q: '{q}' -> Route: {route}")
    if route != expected: failed += 1

if failed == 0:
    print("\n🎉 All Router Tests Passed!")
else:
    print(f"\n⚠️ {failed} Tests Failed.")
