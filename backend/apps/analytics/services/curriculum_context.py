from typing import Optional


def get_curriculum_constants_for_grade(grade_level: Optional[int] = None) -> str:
    """
    Return grade-appropriate curriculum knowledge for the AI prompt.
    Uses the exam's grade_level to scope the diagnosis to the correct
    Vietnamese 2018 national curriculum (GDPT 2018).
    """
    base = """
### 📚 KIẾN THỨC CHƯƠNG TRÌNH (CURRICULUM CONSTANTS)

**Hệ thống chấm điểm:**
- Thi theo barem: mỗi bước đúng được điểm thành phần (chia 0.25).
- TMĐK (Thỏa mãn Điều kiện Xác định): BẮT BUỘC khi bài có căn thức hoặc phân thức. Thiếu TMĐK = mất 0.25 điểm. Đây là LỖI TRÌNH BÀY, không phải lỗi kiến thức.

**Phân nhóm theo điểm (chuẩn Bộ GD&ĐT):**
  Giỏi: ≥ 8.0 | Khá: ≥ 6.5 | Trung bình: ≥ 5.0 | Yếu: < 5.0
"""

    grade_specific = {
        6: """
**Chương trình Toán Lớp 6 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Số tự nhiên: Phép chia có dư, ước và bội, số nguyên tố và hợp số. Lưu ý: 0 và 1 KHÔNG phải số nguyên tố.
- Số nguyên: Cộng trừ nhân chia số nguyên, quy tắc dấu ngoặc.
- Phân số: Rút gọn, quy đồng mẫu, cộng trừ nhân chia phân số.
- Hình học: Điểm, đoạn thẳng, góc, tia. Chu vi và diện tích hình chữ nhật, hình vuông, tam giác.
- Thống kê: Đọc và vẽ biểu đồ cột, bảng số liệu cơ bản.
""",
        7: """
**Chương trình Toán Lớp 7 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Số hữu tỉ và số thực: Cộng trừ nhân chia số hữu tỉ, tỉ lệ thức, đại lượng tỉ lệ thuận/nghịch.
- Biểu thức đại số: Đơn thức, đa thức một biến. Cộng trừ đa thức, nhân đơn thức với đa thức.
- Phương trình: Phương trình bậc nhất một ẩn, giải và biện luận.
- Hình học: Quan hệ giữa các đường thẳng (song song, vuông góc). Tam giác bằng nhau (3 trường hợp). Tam giác cân, đều, vuông.
- Thống kê: Số trung bình cộng, số trung vị, biểu đồ tần số, tần suất.
- Xác suất: Xác suất thực nghiệm (tần suất quan sát).
""",
        8: """
**Chương trình Toán Lớp 8 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Đại số: Nhân đa thức với đa thức, 7 hằng đẳng thức đáng nhớ (A±B)², (A+B)(A-B), (A±B)³...
- Phân thức đại số: Rút gọn, cộng trừ nhân chia phân thức. BẮT BUỘC: TMĐK (mẫu ≠ 0) khi rút gọn phân thức.
- Phương trình: Phương trình bậc nhất, phương trình tích, phương trình chứa ẩn ở mẫu (kèm ĐKXĐ).
- Bất phương trình: Bất phương trình bậc nhất một ẩn, biểu diễn tập nghiệm trên trục số.
- Hình học: Tứ giác (hình bình hành, hình chữ nhật, hình thoi, hình vuông, hình thang). Diện tích các hình.
- Hình học không gian: Hình lăng trụ, hình chóp — thể tích và diện tích xung quanh.
""",
        9: """
**Chương trình Toán Lớp 9 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Căn bậc hai, căn bậc ba: Rút gọn, trục căn thức. BẮT BUỘC: TMĐK (biểu thức dưới căn ≥ 0).
- Hàm số và đồ thị: y = ax + b (đường thẳng), y = ax² (parabol). Xác định a, b từ điều kiện.
- Phương trình bậc hai: Công thức nghiệm, hệ thức Vi-ét (x₁+x₂ = -b/a, x₁·x₂ = c/a).
- Hệ phương trình bậc nhất hai ẩn: Phương pháp thế và cộng đại số.
- Xác suất cổ điển: Không gian mẫu Ω (PHẢI là tập hợp với {}), xác suất P(A) = số phần tử thuận lợi / n(Ω).
- Hình học phẳng: Đường tròn — tiếp tuyến, cung, góc nội tiếp, tứ giác nội tiếp.
- Hình học không gian: Hình trụ, hình nón, hình cầu — diện tích và thể tích.

**Kỹ thuật trọng tâm lớp 9:**
- Xét hiệu: Chứng minh A > B bằng cách tính A - B và xét dấu. Đây là kỹ thuật CHUẨN trong SGK. Dừng lại ở bước rút gọn là CHƯA HOÀN THÀNH.
- Số nguyên tố: Số tự nhiên > 1 có đúng 2 ước (1 và chính nó). 1 KHÔNG phải số nguyên tố.
- Không gian mẫu Ω: PHẢI viết dạng tập hợp với dấu ngoặc nhọn {}. Viết n(Ω) = 12 thay vì Ω = {1;2;...;12} = LỖI KÝ HIỆU.
- Chu vi hình tròn: C = πd = 2πR. Nhầm với diện tích S = πR² = LỖI KIẾN THỨC GỐC.
- Bài toán chuyển động: Phải phân biệt THỜI ĐIỂM (6h, 6h30) và THỜI GIAN (= quãng đường / vận tốc). Nhầm 2 khái niệm này = LỖI TƯ DUY.
""",
        10: """
**Chương trình Toán Lớp 10 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Đại số: Mệnh đề, tập hợp, hàm số. Bất phương trình bậc nhất, bậc hai.
- Hàm số: Hàm số bậc nhất, bậc hai. Đỉnh, trục đối xứng, chiều biến thiên.
- Phương trình và hệ phương trình bậc nhất hai ẩn.
- Hình học phẳng Oxy: Vectơ, tọa độ, phương trình đường thẳng, đường tròn, elip.
- Tổ hợp — Xác suất: Quy tắc đếm, hoán vị, chỉnh hợp, tổ hợp. Xác suất cổ điển.
- Thống kê: Số trung bình, phương sai, độ lệch chuẩn, tần suất.
""",
        11: """
**Chương trình Toán Lớp 11 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Hàm số lượng giác: sin, cos, tan, cot — đồ thị và phương trình.
- Dãy số: Cấp số cộng, cấp số nhân — công thức tổng quát và tổng.
- Giới hạn và liên tục (sơ bộ).
- Hình học không gian: Quan hệ song song và vuông góc trong không gian. Hình lăng trụ, hình chóp.
- Tổ hợp — Xác suất: Nhị thức Newton, biến cố độc lập, xác suất có điều kiện.
""",
        12: """
**Chương trình Toán Lớp 12 (GDPT 2018) — Chỉ chẩn đoán trong phạm vi này:**
- Giải tích: Đạo hàm (quy tắc, đạo hàm hàm hợp). Ứng dụng đạo hàm: tiếp tuyến, đơn điệu, cực trị.
- Khảo sát hàm số: Chiều biến thiên, cực trị, tiệm cận, đồ thị.
- Tích phân: Định nghĩa, tính diện tích. Nguyên hàm cơ bản.
- Hình học không gian: Khối đa diện, khối tròn xoay — thể tích, diện tích.
- Số phức: Khái niệm, phép tính, modul, dạng lượng giác.
- Tổ hợp — Xác suất: Nâng cao, bài tập thi ĐH.
""",
    }

    grade_content = grade_specific.get(grade_level, """
**Lưu ý về chương trình:**
- Đây là đề thi cấp THCS/THPT. Chỉ chẩn đoán lỗi trong phạm vi kiến thức của lớp học tương ứng.
- Không đưa ra diagnosis về kiến thức nằm ngoài chương trình của lớp đó.
""")

    return base + grade_content


def get_golden_examples_for_grade(grade_level=None) -> str:
    """Return grade-appropriate golden example for the analytics prompt."""

    # Grade 6–7: integer/fraction/số nguyên tố domain
    example_6_7 = """
### 🎯 GOLDEN EXAMPLE — Output CỦA BẠN phải đạt mức chất lượng này

**VÍ DỤ (Lỗi kiến thức — ERR_001):**
```json
{
  "id": "ERR_001",
  "tag": "Không nhớ bảng số nguyên tố cơ bản (nhầm 27, 1; thiếu 11, 17)",
  "error_type": "kiến thức",
  "fullDescription": "Đề bài yêu cầu: Liệt kê các số nguyên tố từ 1 đến 30.\\n- Học sinh làm: Nhiều biểu hiện khác nhau — thừa số không phải SNT (27, 21, 1), thiếu số SNT (11, 13, 17, 29), hoặc chỉ ghi kết quả mà không liệt kê.\\n- Tắc ở bước: Học sinh chưa nắm vững định nghĩa số nguyên tố (chỉ có đúng 2 ước: 1 và chính nó) và chưa thuộc bảng SNT cơ bản đến 30.",
  "commonMistakes": [
    "Coi 27 là SNT (quên 27 = 3×9)",
    "Coi 1 là SNT (1 chỉ có 1 ước)",
    "Thiếu 11, 13, 17, 29 trong danh sách"
  ],
  "example": "Nhiều học sinh: Liệt kê 2, 3, 5, 7, 9, 11, 13, 17, 19, 21, 23, 27, 29 (thừa 9, 21, 27)",
  "affected_questions": ["3.1"],
  "affectedStudentIds": [1001, 1003, 1005],
  "severity": "high",
  "suggestedActions": [
    {
      "type": "review_concept",
      "title": "Ôn định nghĩa và bảng SNT đến 30",
      "description": "Viết lên bảng: 'SNT = số tự nhiên > 1, chỉ có đúng 2 ước'. Cho học sinh kiểm tra lần lượt từng số từ 2–30 bằng cách thử chia. Nhấn mạnh: 1 không phải SNT, 27=3×9 nên không phải SNT."
    },
    {
      "type": "practice_exercises",
      "title": "Flashcard bảng SNT",
      "description": "Giao học sinh tự lập flashcard 25 số nguyên tố đầu tiên, kiểm tra lại vào đầu tiết sau bằng cách đọc thuộc."
    }
  ]
}
```
"""

    # Grade 8–9: geometry/algebra/probability domain
    example_8_9 = """
### 🎯 GOLDEN EXAMPLE — Output CỦA BẠN phải đạt mức chất lượng này

**VÍ DỤ (Lỗi trình bày — ERR_002):**
```json
{
  "id": "ERR_002",
  "tag": "Viết n(Ω) thay vì liệt kê Ω",
  "error_type": "trình bày",
  "fullDescription": "Đề bài yêu cầu: Viết tập hợp không gian mẫu Ω (liệt kê các kết quả có thể xảy ra).\\n- Học sinh làm: Không liệt kê, ghi thẳng con số n(Ω) = 12.\\n- Tắc ở bước: Sai thuật ngữ. Các con không phân biệt được 'Không gian mẫu' (là tập hợp phải có {}) và 'Số phần tử' (là một con số).",
  "commonMistakes": [
    "Viết n(Ω) = 12 thay vì liệt kê Ω = {1, 2, 3, ..., 12}",
    "Bỏ ngoặc nhọn của tập hợp"
  ],
  "example": "Học sinh 1016: Viết 'n(Ω) = 12' thay vì 'Ω = {1; 2; 3; ...; 12}'",
  "affected_questions": ["Câu 1.2a"],
  "affectedStudentIds": [1029, 1028, 1030, 1021, 1018, 1031, 1022, 1024, 1025, 1016],
  "severity": "high",
  "suggestedActions": [
    {
      "type": "review_concept",
      "title": "Chữa lỗi trực tiếp trên bảng",
      "description": "Viết to 'Ω = {1, 2...}' và 'n(Ω) = 12' cạnh nhau trên bảng để học sinh đối chiếu trực quan sự khác biệt."
    },
    {
      "type": "practice_exercises",
      "title": "Luyện thói quen dùng ngoặc nhọn",
      "description": "Giao 3 câu phép thử cơ bản (gieo súc sắc, bốc bi) yêu cầu chỉ viết không gian mẫu, bắt buộc kiểm tra xem có dấu {} hay không."
    }
  ]
}
```
"""

    # Grade 10–12: calculus/stats/inequality domain
    example_10_12 = """
### 🎯 GOLDEN EXAMPLE — Output CỦA BẠN phải đạt mức chất lượng này

**VÍ DỤ (Lỗi kỹ thuật — ERR_005):**
```json
{
  "id": "ERR_005",
  "tag": "Ngộ nhận & Bỏ dở Chứng minh BĐT",
  "error_type": "kỹ thuật",
  "fullDescription": "Đề bài yêu cầu: Chứng minh biểu thức P > 1.\\n- Học sinh làm: Rút gọn xong P = (√x+1)/√x rồi để trống, hoặc kết luận bừa P>1 mà không chứng minh.\\n- Tắc ở bước: Không có tư duy giải BĐT. Các con không nhớ quy tắc 'Xét hiệu': muốn chứng minh A > B thì phải lấy A - B rồi xét dấu.",
  "commonMistakes": [
    "Dừng lại ở bước rút gọn",
    "Lập luận vòng tròn: 'P > 1 vì tử lớn hơn mẫu' (chưa đủ chặt chẽ)"
  ],
  "example": "Học sinh 1030: Rút gọn đúng P = (√x+1)/√x nhưng sau đó viết 'Vì √x+1 > √x nên P > 1' mà không xét hiệu P - 1",
  "affected_questions": ["Câu 3c"],
  "affectedStudentIds": [1029, 1028, 1030, 1018, 1031, 1017, 1020],
  "severity": "high",
  "suggestedActions": [
    {
      "type": "review_concept",
      "title": "Dạy lại công thức tư duy Xét Hiệu",
      "description": "Công thức hóa trên bảng: 'Đề kêu chứng minh A > B => Việc đầu tiên phải làm: Lấy A - B'."
    },
    {
      "type": "practice_exercises",
      "title": "Thực hành tại chỗ bước 1",
      "description": "Gọi 2 học sinh nhóm Yếu/TB lên bảng, yêu cầu chỉ làm đúng 1 thao tác: Lập phép tính hiệu số P - 1 = 1/√x."
    }
  ]
}
```
"""

    grade_bands = {
        6: example_6_7,
        7: example_6_7,
        8: example_8_9,
        9: example_8_9,
        10: example_10_12,
        11: example_10_12,
        12: example_10_12,
    }

    return grade_bands.get(grade_level, example_8_9)


# Legacy constants for backward compatibility
CURRICULUM_CONSTANTS = get_curriculum_constants_for_grade(9)
GOLDEN_ERROR_EXAMPLES = get_golden_examples_for_grade(9)  # default grade 9
