# Real Caller - API Documentation & Flow

Tài liệu này mô tả chi tiết logic hoạt động (Flow) của từng API lõi trong hệ thống chống lừa đảo Real Caller và cung cấp các Payload mẫu để test trực tiếp trên Swagger hoặc Postman.

Tất cả các API kiểm tra lừa đảo đều quy về một cấu trúc phản hồi **chuẩn phân tầng**:
- `type`: Phân loại trạng thái (`scam`, `spam`, `normal`, `unknown`).
- `scam_info`: Chứa thông tin lừa đảo (nếu `type` là scam/spam).
- `user_info`: Chứa thông tin người dùng app (nếu `type` là normal).

---

## 1. Kiểm tra 1 số điện thoại nhanh (GET `/{phone}`)
**Method:** `GET /api/v1/scam/{phone}`
**Cần Auth:** Không

### 📌 Luồng hoạt động (Flow):
1. Nhận chuỗi phone từ Path URL và tự động chuẩn hóa định dạng (ví dụ: cạo số 0 ở đầu thay bằng `+84`).
2. Query Database tìm trong bảng Blacklist (`ScamNumber`).
    * Nếu có: Trả về trạng thái `scam` hoặc `spam` dựa trên cột độ rủi ro (`risk_level`).
3. Nếu không có trong Blacklist, query DB tìm trong bảng tài khoản (`Users`).
    * Nếu có: Trả về trạng thái `normal` kèm thông tin cơ bản: Tên, email, verify status.
4. Nếu cả 2 đều không có: Trả về `unknown`.

### 🧪 Test Mẫu (Chạy trên trình duyệt/GET request):
```text
http://localhost:8000/api/v1/scam/%2B84123456789
```

---

## 2. Kiểm tra hàng loạt số (POST `/check-phones`)
**Method:** `POST /api/v1/scam/check-phones`
**Cần Auth:** Có (Truyền Access Token vào Header)

### 📌 Luồng hoạt động (Flow):
1. Giải mã Payload nhận vào 1 mảng danh bạ các số điện thoại cần xem xét.
2. Lọc bỏ các số trùng lặp và chuẩn hóa List.
3. *Tối ưu chống N+1 Query:* Thay vì loop từng số chọc DB, hệ thống sử dụng thuật toán `IN` operator để bốc toàn bộ Dữ liệu từ bảng `ScamNumber` và bảng `Users` lên memory.
4. Xây dựng Hash Map `0(1)` để đối chiếu từng số trong mảng trả ra kết quả cực nhanh.
5. Trả về mảng lớn chứa các object với chuẩn phân tầng quen thuộc.

### 🧪 Payload Test Mẫu:
```json
{
  "phones": [
    "+84123456789", 
    "0981112222", 
    "0944555666"
  ]
}
```

---

## 3. Quét chẩn đoán tin nhắn (POST `/check-conversations`)
**Method:** `POST /api/v1/scam/check-conversations`
**Cần Auth:** Có

### 📌 Luồng hoạt động (Flow):
1. Chạy song song 2 luồng: Luồng 1 (Dò theo Số gửi đến) và Luồng 2 (Dò theo Cụm cú pháp tự nhiên).
2. Tương tự như dò danh bạ, lấy mảng tất cả các số có mặt trong mảng conversation đi query `IN` ở DB (Ra kết quả siêu tốc 10ms).
3. Song song đó, gom Cú pháp tin nhắn ném vào `ai_service` (Hugging Face / LLM) để phân tích hành vi.
4. Kết quả của tin nhắn: Ưu tiên cảnh báo. Nếu Hệ thống bảo SĐT bình thường, NHƯNG AI xác nhận Tin nhắn có mùi lừa đảo -> Trả về kết quả `scam` do AI override quyết định.

### 🧪 Payload Test Mẫu:
```json
{
  "conversations": [
    {
      "phone": "0912123123",
      "messages": [
        "Anh ơi cho em vay 5 triệu nhé, mai em gửi luôn",
        "Số tài khoản em: 1234455 VCB nha"
      ]
    },
    {
      "phone": "+84123456789",
      "messages": [
        "Bạn ơi mình hẹn cf ở Phúc Long nhé"
      ]
    }
  ]
}
```

---

## 4. Báo Cáo Gian Lận (POST `/report`)
**Method:** `POST /api/v1/scam/report`
**Cần Auth:** Có (Đóng vai trò người tố cáo)

### 📌 Luồng hoạt động (Flow):
1. Tiếp nhận số bị báo cáo và các bằng chứng (tin nhắn, ảnh chụp, lý do gõ tay).
2. Dò Database:
   * **Nếu Số ĐÃ có trong bảng Blacklist:** Tăng `reportCount` + 1. Lưu hồ sơ tố cáo vào `ScamReport` cho Admin kiểm duyệt. Cuối cùng trả về kết quả cho Client.
   * **Nếu Số CHƯA có trong Blacklist:** Không kết luận vội. Đóng gói đống bằng chứng bắn sang **AI Service (Trí tuệ nhân tạo)**.
3. Nếu nhận định của AI bảo *Là lừa đảo*: Hàm sẽ tự động tạo thẳng 1 dòng vào bảng Blacklist `ScamNumber`. Đánh dấu `is_ai_vetted=True`. Phản hồi báo cáo thành công và cảnh cáo số này ngay.
4. Nếu AI bảo *Không rõ/An Toàn*: Không lưu vào Blacklist để bảo vệ người vô tội. Phản hồi như số bình thường (`unknown` hoặc `normal`). Vẫn lưu log `ScamReport` dạng ẩn để lúc Admin cần thì tra lại.

### 🧪 Payload Test Mẫu:
```json
{
  "phone": "0988777666",
  "type": "investment",
  "description": "Số này gọi cho tôi bảo tải app để nhận thưởng hoa hồng khi thả tim Tiktok.",
  "messages": [
    {
      "sender": "0988777666",
      "content": "Bạn hãy click đường dẫn sau để đăng ký tài khoản tham gia nhé."
    }
  ],
  "evidence_urls": [
    "https://example.com/screenshot.png"
  ]
}
```

---

## 5. Trợ Lý Chatbot Hybrid AI (POST `/chatbot/chat`)
**Method:** `POST /api/v1/chatbot/chat`
**Cần Auth:** Có

### 📌 Luồng hoạt động (Flow Hybrid AI Mới Vừa Thêm):
1. Nhận tin nhắn chat tự nhiên từ Client + Lịch sử (tối đa 5 câu text gần nhất làm ngữ cảnh).
2. **Lớp 1 (NLP Intent):** Sử dụng LLM (Gemini) để đọc hiểu ý đồ người dùng. Trích xuất chính xác 1 SĐT từ đống chữ lộn xộn. (Regex Backup nếu AI lag).
3. **Lớp 2 (Core Verify):** Đem SĐT đào được chọc Database lấy Data chuẩn của hệ thống Real Caller (`scam_info`, `user_info`).
    * Nếu không có thông tin (Lớp 2.5): Ném chính cái đoạn chat mà SĐT kia nói vào hệ AI HuggingFace để tự động khám nghiệm nội dung bằng chữ xem có phải là cú lừa không.
4. **Lớp 3 (Generative Text):** Giao kết quả tổng hợp được cho con LLM (Gemini) để nó soạn ra 1 câu trả lời chuẩn ngữ pháp, nghe như người thật, bám sát các câu hỏi ở ngữ cảnh `history` cũ rồi trả json về.

### 🧪 Payload Test Mẫu (Nhớ gắn GEMINI_API_KEY ở .env):

**Case 1: Ý định mập mờ, bắt bẻ Chatbot**
```json
{
  "message": "Số lúc nãy mình hỏi là lừa đảo à?",
  "history": [
    {
      "role": "user",
      "content": "Chào bạn, cho mình hỏi số 0944555666 này là của ai?"
    },
    {
      "role": "model",
      "content": "Theo ghi nhận, số 0944555666 là lừa đảo vay tín dụng nhé."
    }
  ]
}
```

**Case 2: Cài luôn tin nhắn rác để thử trình Lớp 2.5 (AI Fallback)**
```json
{
  "message": "Chatbot ơi, số 0111222333 vừa nhắn cho tôi bảo 'Đăng nhập vào link m.bank-viet.com để đổi mật khẩu thẻ ATM' là lừa đảo phải không?",
  "history": []
}
```
