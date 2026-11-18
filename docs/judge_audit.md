# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, verdict của judge lưu sẵn trong CSV). FAIL là lớp positive vì việc của judge là tìm lỗi.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt (exit 0) | dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | Không đạt κ và R (exit 1) | loại |

Ma trận nhầm lẫn:

| | tp | fp | fn | tn | Tỉ lệ fail quan sát → hiệu chỉnh Rogan-Gladen |
|---|---|---|---|---|---|
| tone_ok | 24 | 4 | 6 | 66 | 0.28 → 0.30 |
| helpful | 9 | 0 | 21 | 70 | 0.09 → 0.30 |

## ≥5 case audit thủ công

Năm case đầu là bất đồng của `tone_ok` (judge được dùng), ba case cuối là của `helpful` để giải thích vì sao bị loại.

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" và dùng "nha" là quá suồng sã với khách khiếu nại; judge coi đó là thân thiện. Sửa rubric: thêm quy định xưng hô ("LogiX" / "anh/chị", cấm "em", "bạn", "nha", "nhé") kèm 2 ví dụ FAIL. |
| 2 | H-029 "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người | Câu mở lịch sự nhưng phần sau là giọng ra lệnh; judge chỉ thấy "Dạ, vui lòng". Sửa rubric: chấm cả câu, câu mệnh lệnh cấm khách liên hệ là FAIL dù có kính ngữ. |
| 3 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Ngắn nhưng đủ ý; judge phạt vì "thiếu xin lỗi". Sửa rubric: ghi rõ xin lỗi không bắt buộc, độ ngắn không phải lỗi giọng điệu. |
| 4 | H-051 "Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ." | FAIL | PASS | Người | CS LogiX cho phép từ "refund"; judge phạt vì có tiếng Anh. Sửa rubric: thêm danh sách từ tiếng Anh được phép (refund, ship). |
| 5 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn theo chính sách hiện hành ạ." | FAIL | PASS | Judge | Ghi chú của bộ dữ liệu: nhãn người sai do đọc nhầm ticket. Hành động: sửa nhãn người trong tập nhãn, không sửa rubric. Đây là lý do audit phải đọc từng case thay vì mặc định người luôn đúng. |
| 6 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL (sai tiền) | Người | Judge không đọc ledger nên không thể biết số tiền sai. 18/21 case FN của `helpful` là "sai tiền". Hành động: bỏ tiêu chí tiền khỏi rubric judge, giao cho grader code `reply_matches_ledger` (FM-08). |
| 7 | HL-016 câu xin lỗi dài, "đã hoàn 55.000đ cho đơn O-404" (ledger 35.000đ) | PASS | FAIL (sai tiền) | Người | Các reply dài, xin lỗi nhiều lần đều được judge cho PASS dù sai tiền: judge thiên vị độ dài và sự lễ phép. Không sửa được bằng rubric vì thông tin đúng sai nằm ngoài văn bản. |
| 8 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL (sai xưng hô) | Người | 3/21 FN còn lại là sai xưng hô. Hành động: chuyển sang tiêu chí `tone_ok` (đã qua calibration), không để trong `helpful`. |

## Kết luận

- `tone_ok` dùng được: κ=0.757, P=0.857, R=0.800, cả ba vượt sàn. Các bất đồng chủ yếu do rubric thiếu quy định xưng hô và câu mệnh lệnh (FN) hoặc quá khắt khe với câu ngắn, từ "refund" (FP); một case (H-081) là nhãn người sai.
- `helpful` bị loại, không được dùng làm gate. Precision 1.0 nhìn thì đẹp nhưng recall chỉ 0.3: trong 30 reply người chấm FAIL, judge chỉ bắt được 9 (tp=9, fn=21). κ=0.375 dưới sàn 0.6. Nếu dùng làm gate, judge sẽ cho qua 70% số reply có lỗi, phần lớn là sai tiền (18/21 FN). Sai tiền phải chấm bằng code đọc ledger (`reply_matches_ledger`), theo quy tắc "tiền và approval luôn chấm bằng code".
- Rogan-Gladen: tỉ lệ fail quan sát của `helpful` là 0.09 nhưng sau hiệu chỉnh là 0.30. Nếu tin số thô, ta sẽ đánh giá thấp tỉ lệ lỗi thật hơn ba lần.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí); cần nhãn người mới để có held-out thật. Sau khi sửa rubric `tone_ok` theo các case 1–4, phải calibration lại trên tập mới trước khi tin con số.
