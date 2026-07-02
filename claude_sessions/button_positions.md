# KHUx v1.0.1 Button Positions (OnePlus 3T, Landscape 1794x1080)

## Intro Movie
- SKIP button: 100, 50 (top-left corner)

## Title Screen
- Tap 1 (skip transition): 897, 540
- Tap 2 (Start Game): 897, 540 (same position, 1s after tap 1)

## EULA Screen
- Accept: 1350, 950

## Birth Date Registration
- Register (opens confirmation): 897, 648
- Confirmation dialog Register: 1120, 648
- Confirmation dialog Edit: 674, 648

## Download Screen
- Download button: 897, 864

## Download Complete / Jewels Screen
- Collect button: 897, 864 (same as download button)

## Name Registration Screen
- Name input field: 897, 520
- OK button: 897, 1037 (center x, ~4% from bottom)
- Input method: tap field → `adb input text "Name"` → `adb input keyevent 66` (Enter) → tap OK

## Avatar Editor
- Decision/Confirm button: 1200, 1010
- Avatar confirm OK: 1087, 1026 (center+5% X, 5% from bottom Y)

## Cutscene (inline LWF, within SceneUnionRegister)
- SKIP button: 100, 50 (top-left corner)
- Note: Only tap ONCE — extra taps can close subsequent modals

## Union Selection
- Union Info "I understand" OK: 897, 1037 (center x, bottom — same as Name OK)
- Union option (first/top Unicornis): 897, 216 (center x, ~20% from top)
- "Join Unicornis?" Confirm OK: 1162, 815

## Tutorial Flow Summary
1. Intro movie → SKIP (100, 50)
2. Title → tap twice (897, 540) with 1s gap
3. EULA → Accept (1350, 950)
4. Birthday → Register (897, 648) + Confirm (1120, 648)
5. Download → Download (897, 864) → wait → Collect (897, 864)
6. Name → field (897, 520) + type + Enter + OK (897, 1037)
7. Avatar → Confirm (1200, 1010) + OK (1087, 1026)
8. Cutscene 1 → SKIP (100, 50)
9. Union info → OK (897, 1037)
10. Union select → Unicornis (897, 216)
11. Join confirm → OK (1162, 815)
12. Cutscene 2 → SKIP (100, 50)
13. Tutorial battle → (black screen — under investigation)
