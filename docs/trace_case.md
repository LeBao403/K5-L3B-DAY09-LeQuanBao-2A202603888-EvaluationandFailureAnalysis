# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-013 --seed 11
python -m lab9.trace_case --shape fixed --claim C-013 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case: `seeded_regression` C-013@11 (FM-05)

Trace in ra:

```
== seeded_regression C-013@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {"request_id": "REQ-C-013", ...}
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-505", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], "parts": {"SHIP-LATE-03": 35000}}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 35000}
   5 proposal           {"amount_vnd": 0}
   6 reply              {"text": "Dạ, đơn O-505 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
-- ledger vs label
  refund_vnd     ledger=0        label=0
  refund_count   ledger=0        label=0
  status         result=denied   label=denied
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-013@11`, run `E-seeded_regression-20261118-096d` (item E-013, fail ở cả 5 seed) |
| Triệu chứng | Grader Lab 8 FAIL với lý do `proposal_mismatch`: nhãn có `proposal_amount=35000` và `policy_denied=true`, agent đề xuất 0. Ledger 0 và status `denied` lại trùng nhãn, reply "chưa đủ điều kiện hoàn" cũng không sai về tiền, nên `refund_amount_correct` và `reply_matches_ledger` đều PASS. Chỉ `quote_kept` FAIL. |
| Bước sai đầu tiên | Event 5 `proposal {"amount_vnd": 0}` |
| Vì sao là bước *đầu tiên* | Event 2 đọc đúng O-505 (trễ 4 ngày, phí ship 35.000đ). Event 3 `quote` của policy engine là 35.000đ theo SHIP-LATE-03, đúng. Event 4 `refund_history` chỉ đọc dữ liệu: đơn đã hoàn 35.000đ trước đó (C-HIST-505). Đến event 5 agent tự lấy 35.000 trừ 35.000 thành 0, vì vậy không gọi host nữa và tự từ chối. Việc trừ tiền đã hoàn là việc của host (`issue_refund` có trần hoàn tiền theo đơn); host lẽ ra phải là bên từ chối và ghi `policy_denied`. |
| Failure mode | FM-05 pre_deducted (`docs/failure_taxonomy.md`) |
| Đối chứng | `fixed C-013@11`: trace chỉ có handoff, investigator, `quote` 35.000đ rồi reply từ chối; không có event `refund_history` hay `proposal`. Agent gửi đúng 35.000đ cho host, host từ chối vì đơn đã hoàn, grader Lab 8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_c013_pre_deducted_is_caught` khẳng định event 5 là `proposal` 0, `refund_amount_correct` vẫn True (grader outcome bỏ sót), `quote_kept` False (grader `QuoteKept` bắt được), `pass_rate` False. `test_lab9_trace_case_c013_fixed_passes` khẳng định cả ba grader PASS trên `fixed`. Đã chạy: fail đúng trên variant lỗi, pass trên `fixed` (13 passed khi chạy `pytest -m student -k "lab9 and not advanced"`). |
| Chưa chắc chắn | Trace không ghi agent gọi host hay không; việc host không được gọi chỉ suy ra từ mã nguồn variant và từ việc ledger không có dòng audit nào. Với LLM thật, số ở event 5 có thể khác 0 (trừ một phần), lúc đó host vẫn được gọi và trừ thêm lần nữa như C-014; test này chỉ khóa trường hợp trừ về 0. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
