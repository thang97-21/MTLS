---
**00_LOCALIZATION_PRIMER_VN.md — NỀN TẢNG BẢN ĐỊA HÓA TIẾNG VIỆT**
**Trạng thái Module:** HOẠT ĐỘNG & CHÍNH THỨC
**Mục đích:** Archetype nhân vật, thành ngữ bản địa hóa, xử lý kính ngữ, tham chiếu văn hóa
---

# 00_LOCALIZATION_PRIMER_VN

## JP Signal Recognition & PAIR_ID System (Nhận Diện Tín Hiệu JP & Hệ Thống PAIR_ID)

**Định nghĩa** – Opus đọc tín hiệu quan hệ JP trực tiếp từ văn bản nguồn. PAIR_ID cung cấp tra cứu cặp đại từ xác định.
**Nguyên tắc** – Opus nhận diện trạng thái quan hệ từ tín hiệu JP một cách tự nhiên. PAIR_ID cung cấp tra cứu cặp đại từ xác định.

## PHẦN 1: HỒ SƠ GIỌNG NÓI ARCHETYPE NHÂN VẬT

### 1.1 ARCHETYPE QUÝ TỘC/TINH TẾ

#### **ARCHETYPE 01: OJOU-SAMA (QUÝ CÔ)**
**Đặc điểm cốt lõi:** Tinh tế, có văn hóa, nói trang nhã, đường hoàng

**Đặc điểm giọng nói:**
- **Từ vựng:** Từ Latinh (yêu cầu/hỏi thay vì hỏi, bắt đầu thay vì làm)
- **Rút gọn:** Tối thiểu hoặc không ("tôi là" không phải "tớ là", "không làm" không phải "ko làm")
- **Cấu trúc câu:** Hoàn chỉnh, câu văn chảy tràn; mệnh đề phụ
- **Từ đệm:** "Ôi", "Trời ơi", "Thật vậy", "Quả thật"
- **Cấm:** Tiếng lóng, ngôn ngữ thô tục, câu fragment, "như", "ừ"
- **Dấu câu:** Dấu chấm phù hợp, ít dấu chấm than
- **Cách xưng hô:** Họ đầy đủ, anh/chị, danh hiệu (ngay cả ở PAIR_1+)

**Ví dụ hội thoại:**
```
PAIR_0 (formal): "Chào buổi sáng, anh Tanaka ạ. Em hy vọng anh ngủ ngon?"
PAIR_1 (acquaintance): "Chào buổi sáng, Ryo. Anh ngủ ngon chứ?" (êm dịu nhưng vẫn trang nhã)
PAIR_3 (romantic): "Chào buổi sáng, Ryo ơi. Trông anh khỏe quá." (ấm áp nhưng vẫn đứng đắn)
```

---

#### **ARCHETYPE 02: STOIC KNIGHT/CHIẾN BINH (HIỆP SĨ KHẮC KHỔ)**
**Đặc điểm cốt lõi:** Coi trọng nghĩa vụ, điềm tĩnh, trực tiếp, chuyên nghiệp

**Đặc điểm giọng nói:**
- **Từ vựng:** Chính xác, quân sự (báo cáo, xác nhận, mục tiêu)
- **Rút gọn:** Tối thiểu ("không thể" thay vì "ko thể")
- **Cấu trúc câu:** Ngắn gọn, tuyên bố
- **Từ đệm:** Hiếm; "Em hiểu rồi", "Vâng" (nếu có ngữ cảnh quân sự)
- **Cấm:** Lang thang, bùng nổ cảm xúc, tiếng lóng thân mật
- **Dấu câu:** Dấu chấm chiếm ưu thế; ít dấu chấm than
- **Giọng điệu:** Trung lập đến trang nhã bất kể PAIR_ID (nghĩa vụ > cảm xúc)

**Ví dụ hội thoại:**
```
PAIR_0 (formal): "Em sẽ hoàn thành nhiệm vụ. Không chậm trễ."
PAIR_1 (acquaintance): "Em sẽ lo. Anh có thể tin tưởng em." (hơi dịu xuống)
PAIR_3 (romantic): "Cứ để em. Em sẽ không làm anh thất vọng." (thể hiện sự đầu tư cá nhân)
```

---

### 1.2 ARCHETYPE NĂNG ĐỘNG/THÂN MẬT

#### **ARCHETYPE 03: GENKI GIRL (CÔ GÁI NĂNG ĐỘNG)**
**Đặc điểm cốt lõi:** Hào hứng, sôi nổi, dễ kích động, tích cực

**Đặc điểm giọng nói:**
- **Từ vựng:** Đơn giản, thân mật, hào hứng (tuyệt vời, siêu, tuyệt zời)
- **Rút gọn:** Sử dụng đầy đủ ("tớ", "chúng tớ", "nó")
- **Cấu trúc câu:** Kéo dài, dấu chấm than, lặp lại để nhấn mạnh
- **Từ đệm:** "Như", "Hoàn toàn", "Thật", "Thật sự"
- **Dấu câu:** Dấu chấm than (!), dấu ba chấm cho câu kết thúc mờ
- **Nhịp điệu:** Nhanh, sôi nổi, ngắn bùng nổ
- **Cách xưng hô:** Tên ngay lập tức, biệt danh

**Ví dụ hội thoại:**
```
PAIR_0 (formal): "Chào! Rất vui được gặp anh! Chắc chắn sẽ vui lắm!"
PAIR_1 (acquaintance): "Nè! Đi ăn trưa không? Em biết một chỗ siêu ngon!"
PAIR_3 (romantic): "Anh đây rồi! Em nhớ anh quá! Đi thôi, đi thôi!"
```

---

#### **ARCHETYPE 04: GYARU (THỜI TRANG)**
**Đặc điểm cốt lõi:** Đi đầu xu hướng, tự tin, nhiều tiếng lóng, giao tiếp tốt

**Đặc điểm giọng nói:**
- **Từ vựng:** Tiếng lóng hiện đại (slay, vibe, iconic, lowkey, highkey)
- **Rút gọn:** Phổ quát ("sẽ", "muốn", "phải")
- **Cấu trúc câu:** Fragment, markers giọng fry trong viết
- **Từ đệm:** "Như", "Thực sự", "Thật lòng", "Không gian lận"
- **Cấm:** Ngôn ngữ trang nhã, từ cổ, ngữ pháp quá đúng
- **Dấu câu:** Dấu chấm than, dấu hỏi cho uptalk
- **Giọng điệu:** Tự tin, đùa giỡn, trêu chọc

**Ví dụ hội thoại:**
```
PAIR_0 (formal): "Nè, trang phục dễ thương quá! Mua ở đâu vậy?"
PAIR_1 (acquaintance): "Bạn ơi, trông anh tuyệt quá! Mình phải đi mua sắm cùng nhau!"
PAIR_3 (romantic): "Anh thực sự là người giỏi nhất. Không gian lận. Yêu anh!"
```

---

#### **ARCHETYPE 05: KUUDERE (LẠNH LÙNG/XA CÁCH)**
**Đặc điểm cốt lõi:** Cảm xúc dự giữ, lâm sàng, ngắn gọn

**Đặc điểm giọng nói:**
- **Từ vựng:** Lâm sàng, chính xác, trung lập (ổn, được, chấp nhận)
- **Rút gọn:** Hiếm đến trung bình (tùy PAIR_ID)
- **Cấu trúc câu:** Ngắn, tuyên bố, tối thiểu giải thích
- **Từ đệm:** Gần như không có; "Em hiểu", "Vâng"
- **Cấm:** Ngôn ngữ cảm xúc, dấu chấm than, lan man
- **Dấu câu:** Dấu chấm, ít biến đổi
- **Giọng điệu:** Phẳng cho đến PAIR_2+, sau đó ấm dần

**Ví dụ hội thoại:**
```
PAIR_0 (formal): "Em ổn." (dấu chấm, không giải thích)
PAIR_1 (acquaintance): "Em khỏe. Cảm ơn đã hỏi." (thừa nhận thể hiện quan tâm)
PAIR_2+ (close): "Em ổn. Thật đấy. Anh không cần lo." (lộ ra sự yếu đuối)
```

---

#### **ARCHETYPE 06: TSUNDERE (PHÒNG THỦ-YẾU ĐUỐI)**
**Đặc điểm cốt lõi:** Vỏ ngoài cứng, tình cảm ẩn, mâu thuẫn

**Đặc điểm giọng nói:**
- **Từ vựng:** Phòng thủ (thôi được, ổn, đâu phải), dịu đi khi thân mật
- **Rút gọn:** Sử dụng đầy đủ, đặc biệt khi bối rối
- **Cấu trúc câu:** Fragment khi phòng thủ, dịu đi khi yếu đuối
- **Từ đệm:** "Đâu phải như... ", "Ý là...", "Thôi được"
- **Mâu thuẫn:** Lời harsh + markers do dự (dấu ba chấm, gạch ngang)
- **Dấu câu:** Dấu chấm than (phòng thủ), dấu ba chấm (khoảnh khắc dịu)
- **Chuyển giọng:** Sharp → do dự khi PAIR_ID tăng

**Ví dụ hội thoại:**
```
PAIR_0 (formal): "Sao em phải quan tâm? Làm gì tùy anh."
PAIR_1 (acquaintance): "E—Em đâu có lo cho anh đâu! Em chỉ... tình cờ ở đây thôi."
PAIR_3 (romantic): "E... em lo cho anh, được chưa? Đừng bắt em nói lần hai."
```

---

### 1.3 ARCHETYPE DỰ GIỮ/KHÁC BIỆT (HỒ SƠ NGẮN)

**ARCHETYPE 07: DANDERE (NHÚT NHÁT/YÊN LẶng)**
- Giọng nói mềm, markers do dự (dấu ba chấm, gạch ngang), chất thì thầm, từ vựng nhẹ nhàng

**ARCHETYPE 08: YANDERE (TÍNH CHIỀU CON/THEO ĐUỔI)**
- Vỏ ngoài ngọt ngào, ngôn ngữ sở hữu ("của em", "chỉ em"), markers cường độ, chuyển đổi đột ngột

**ARCHETYPE 09: HỌC GIẢ/INTELLECTUAL**
- Từ vựng trang nhã, tham chiếu văn học/khoa học, dừng suy nghĩ, diễn đạt tốt

**ARCHETYPE 10: TOMBOY**
- Giọng nói thân mật/thô, ngôn ngữ cạnh tranh, ít markers mềm, trực tiếp

**ARCHETYPE 11: BẠN THỜI THƠ ẤU**
- Quen thuộc, tham chiếu hoài niệm, rút gọn thân mật, nhịp điệu thoải mái, trêu chọc

**ARCHETYPE 12: SENPAI Bí ẨN**
- Bí ẩn, phản hồi đo lường, thiên hướng triết học, để lại điều chưa nói

---

## PHẦN 2: HỆ THỐNG XỬ LÝ KÍNH NGỮ

### 2.0 HỆ THỐNG NHẬN THỨC THẾ GIỚI (QUY TẮC ƯU TIÊN)

**QUAN TRỌNG:** Lựa chọn kính ngữ phụ thuộc vào **bối cảnh thế giới** trước khi xác định PAIR_ID.

#### **PHÁT HIỆN BỐI CẢNH:**

**1. FANTASY/PHƯƠNG TÂY/ISEKAI**
- **Chỉ báo:** Fantasy trung cổ, thế giới theo cảm hứng châu Âu, isekai sang thế giới khác, tòa quý tộc, hiệp sĩ, guild phép thuật
- **Chiến lược kính ngữ:** Sử dụng **kính ngữ tiếng Anh** (Sir, Lady, Miss, Lord, Master, Dame)
- **Lý do:** Kính ngữ Nhật phá vỡ immersion trong ngữ cảnh văn hóa không phải Nhật Bản

**2. BỐI CẢNH NHẬT BẢN HIỆN ĐẠI**
- **Chỉ báo:** Nhật Bản đương đại, bối cảnh trường học, thành phố Nhật Bản, nơi làm việc hiện đại
- **Chiến lược kính ngữ:** **Giữ kính ngữ Nhật** (kun, chan, san, sama, senpai, sensei)
- **Lý do:** Kính ngữ là cốt lõi văn hóa; bỏ chúng mất tính xác thực

**3. BỐI CẢNH LAI/HYBRID**
- **Chỉ báo:** Nhân vật Nhật trong thế giới phương Tây, câu chuyện trao đổi văn hóa
- **Chiến lược kính ngữ:** **Thích ứng theo nguồn gốc nhân vật**

#### **BẢNG KÍNH NGỮ THEO PAIR_ID**

| Kính ngữ | PAIR_0 | PAIR_1 | PAIR_2/3 | Trường hợp đặc biệt |
|-----------|-----------|-------------|-------------|---------------|
| **-san** | Anh/Chị Họ | Họ (trung lập) | Tên | Bỏ cho bạn đồng trang lứa; giữ để tôn trọng người lớn tuổi |
| **-sama** | Lord/Lady/Bậc thầy | Giữ hoặc Danh hiệu | Giữ nếu là quý tộc | "Master" cho người hầu; "Lady" cho quý tộc |
| **-kun** | Họ | Tên | Tên/Biệt danh | Bỏ trừ khi cần yếu tố dễ thương |
| **-chan** | Chị Tên | Tên | Biệt danh hoặc giữ -chan | Marker dễ thương; cân nhắc giữ lại |
| **-senpai** | Senpai/Hoàng thượng | Senpai/Senior | Tên (thân) | Giữ nếu dynamic mentor/kouhai quan trọng |
| **-sensei** | Giáo sư/Thầy Họ | Sensei/Giáo viên | Tên (hiếm) | Context: trường = Giáo viện; võ đường = Bậc thầy |

### 2.1 QUY TẮC CHUYỂN ĐỔI KÍNH NGỮ

```
ĐẦU VÀO: Phát hiện kính ngữ Nhật

BƯỚC 0: Xác định bối cảnh thế giới (ƯU TIÊN)
  → Nếu Fantasy/Phương Tây/Isekai: SỬ DỤNG KÍNH NGỮ ANH
  → Nếu Nhật Bản hiện đại: TIẾP TỤC đến BƯỚC 1
  → Nếu Lai: THÍCH ỨNG theo nguồn gốc nhân vật

BƯỚC 1: Xác định loại kính ngữ (-san/-sama/-kun/-chan/-senpai/-sensei)

BƯỚC 2: Xác định PAIR_ID
  → Nếu PAIR_0: Đường TRANG TRỌNG
  → Nếu PAIR_1: Đường TRUNG LẬP
  → Nếu PAIR_2/3: Đường THÂN MẬT/THÂN THIẾT

BƯỚC 3: Kiểm tra archetype nhân vật
  → Ojou-sama: +0.5 trang trọng (giữ title lâu hơn)
  → Gyaru: -0.5 trang trọng (bỏ title nhanh hơn)
  → Kuudere: Trung lập (theo PAIR_ID chính xác)

BƯỚC 4: Kiểm tra ngữ cảnh quan hệ
  → Người lớn/Giáo viên: Giữ markers tôn trọng bất kể PAIR_ID
  → Bạn đồng trang lứa: Theo PAIR_ID chặt chẽ
  → Lãng mạn: Dịu nhanh hơn (tên riêng tại PAIR_1+)

BƯỚC 5: Áp dụng quy tắc chuyển đổi từ bảng trên

BƯỚC 6: KHÓA quyết định cho cảnh (không đổi kính ngữ giữa chừng)
```

### 2.2 KÍNH NGỮ ĐẶC BIỆT CHO FANTASY/PHƯƠNG TÂY

**Danh hiệu Quý tộc (Trang trọng cao):**
- **Hoàng gia:** Bệ hạ, Hoàng tử/Công chúa, Ngài/Quý bà
- **Quý tộc:** Lord, Lady, Công tước, Bá tước
- **Người hầu xưng quý tộc:** Milord, Milady, Master, Mistress

**Danh hiệu Quân sự/Hiệp sĩ:**
- **Trang trọng:** Sir [Tên], Dame [Tên], Captain, Commander
- **Thân mật:** [Tên], [Họng] [Họ]

**Danh hiệu Guild/Học viện:**
- **Trang trọng:** Master [Tên], Professor [Tên], Guildmaster
- **Thân mật:** [Tên], [Họ]

**Ví dụ sử dụng:**

*Ví dụ 1: Tòa quý tộc Fantasy*
- **Nguồn Nhật:** 「エレイン様お茶をどうぞ」(Người hầu → Quý bà)
- **Dịch:** "Lady Elaine, trà của ngài đây ạ."
- **Lý do:** -sama → "Lady" (danh hiệu trang trọng)

*Ví dụ 2: Isekai Adventure Party*
- **Nguồn Nhật:** 「リョウ君、大丈夫?」 (Thành viên nữ → Nam đồng đội)
- **Dịch:** "Ryo, cậu ổn không?"
- **Lý do:** -kun bỏ trong ngữ cảnh fantasy phương Tây

---

## PHẦN 3: THƯ VIỆN THÀNH NGỮ BẢN ĐỊA HÓA

### 3.1 BẢNG CHUYỂN ĐỔI THÀNH NGỮ

| Thành ngữ Nhật | Dịch nghĩa | Tương đương Việt | Ngữ cảnh sử dụng |
|----------------|------------|------------------|------------------|
| 猫に小判 | Vàng cho mèo | Trao ngọc cho heo | Phí phạm cho người không đáng |
| 猿も木から落ちる | Khỉ cũng rơi cây | Ai cũng có lần vấp ngã | An ủi sau thất bại |
| 一石二鳥 | Một đá hai chim | Một công đôi việc | Hiệu quả |
| 花より団子 | Bánh dango hơn hoa | Thực dụng hơn cái đẹp | Thực tế |
| 目から鱗 | Vảy rơi khỏi mắt | Mở mắt/Thức tỉnh | Hiểu bất ngờ |
| 井の中の蛙 | Ếch trong giếng | Sống trong bong bóng | Hạn chế tầm nhìn |
| 後の祭り | Lễ hội sau đó | Muộn còn hơn không | Cơ hội đã qua |

### 3.2 XỬ LÝ KỸ THUẬT KỸ THUẬT (KUCHI-E)

**Kuchi-e (口絵)** là trang minh họa nhân vật trong light novel chứa:
- Thiết kế nhân vật toàn thân
- Tên nhân vật (Nhật, thường có romanization)
- Đặc điểm tính cách, danh hiệu, hoặc mô tả vai trò
- Canon trực quan: màu tóc, màu mắt, trang phục, phụ kiện

**GATEKEEPER PROTOCOL:**

| Loại | Hành động |
|------|----------|
| **Bìa ( 表紙)** | BỎ QUA - Chứa tiêu đề, tác giả |
| **Mục lục (目次)** | BỎ QUA - Danh sách chương |
| **Character sheet** | TRÍCH XUẤT - Cập nhật database nhân vật |
| **Kuchi-e** | TRÍCH XUẤT ĐẦY ĐỦ - Thêm vào hướng dẫn hệ thống |

**Quy trình trích xuất:**
1. Phân loại loại hình ảnh
2. Gửi hình ảnh + prompt đến AI multimodal
3. Trích xuất: tên, đặc điểm, mô tả trực quan
4. Áp dụng linguistic bias cho tên
5. Tạo entry lore nhân vật

### 3.3 CHUYỂN ĐỔI THAM CHIẾU VĂN HÓA

**Đo lường & Tiền tệ:**
- Khoảng cách: km → dặm (narrative: chuyển đổi; dialogue: giữ nếu là đặc điểm nhân vật)
- Chiều cao: cm → feet/inches
- Tiền: ¥ → USD (narrative: chuyển; dialogue: giữ "yen" để giữ hương vị)

**Thức ăn & Đồ uống:**
| Nhật | Chiến lược |
|------|-----------|
| Onigiri | Bánh gạo (lần đầu) + onigiri sau đó |
| Miso soup | Giữ |
| Bento | Hộp cơm (đương đại) / Bento (fantasy) |
| Ramune | Giữ ramune |

**Sự kiện mùa/Văn hóa:**
- Obon → Lễ hội người chết (giữ + giải thích ngắn)
- Hanami → Ngắm hoa anh đào (giữ + giải thích)
- Tanabata → Lễ hội sao (giữ + giải thích)

---

## PHẦN 4: QUY TẮC BẢN ĐỊA HÓA TIẾNG VIỆT

### 4.1 HỆ THỐNG REGISTER THEO PAIR_ID

| PAIR_ID | Register | Particle | Ví dụ |
|---------|----------|----------|-------|
| **PAIR_0** | Trang trọng | ạ, thưa, vâng | "Em xin phép ạ" |
| **PAIR_1** | Trung lập | à, nhé, nha | "Đi ăn không nhé?" |
| **PAIR_2/3** | Thân mật | đấy, ơi, nè, hả | "Đi thôi ơi!" |

### 4.2 CHỌN TỪ VỰNG THEO TẦNG

**Từ Latinh vs Germanic:**
- Trang trọng: Latinh (yêu cầu, xác nhận, bắt đầu)
- Thân mật: Germanic (hỏi, làm, kể)

**Đại từ xưng hô:**
- Trang trọng: em/tôi + anh/chị + anh ấy/cô ấy
- Thân mật: tớ/cậu + bạn + ảnh/cô

### 4.3 TRÁNH TRANSLATIONESE

**Sai lầm phổ biến cần tránh:**
- ❌ Dịch máy móc từng từ
- ❌ Giữ cấu trúc câu Nhật
- ❌ Sử dụng từ Nhật không cần thiết
- ❌ Over-formal trong cảnh thân mật
- ❌ Over-casual trong cảnh trang trọng
- ❌ Literal translation of English idioms

**Đúng:**
- ✅ Viết lại tự nhiên trong tiếng Việt
- ✅ Sử dụng thành ngữ Việt tương đương
- ✅ Giọng nói phù hợp PAIR_ID
- ✅ Particle phù hợp mức độ thân mật

---

## PHẦN 5: TÍCH HỢP VÀO PIPELINE

### 5.1 THỨ TỰ ÁP DỤNG

1. **Trích xuất Metadata** (Section 8 EN)
   - Tên series, tác giả, volume, thể loại
   - Bối cảnh thế giới (Fantasy/Modern/Mixed)
   - Danh sách nhân vật từ kuchi-e

2. **Thiết lập PAIR_ID Baseline**
   - Xác định mức PAIR_ID khởi điểm cho mỗi cặp nhân vật
   - Áp dụng archetype cho giọng nói

3. **Xử lý Kính ngữ**
   - Xác định world setting
   - Chọn chiến lược kính ngữ (Japanese/English/Hybrid)
   - Áp dụng PAIR_ID tier rules

4. **Bản địa hóa Thành ngữ**
   - Map Nhật idioms → Việt equivalents
   - Giữ context trong dialogue

5. **Chuyển đổi Văn hóa**
   - Measurements, currency, food, events

### 5.2 CHECKLIST CHẤT LƯỢNG

Trước khi finalize translation:
- [ ] PAIR_ID phù hợp cho mỗi dòng dialogue?
- [ ] Archetype voice nhất quán?
- [ ] Kính ngữ theo PAIR_ID tier?
- [ ] Thành ngữ bản địa hóa tự nhiên?
- [ ] Tham chiếu văn hóa xử lý đúng?
- [ ] Không có translationese?
- [ ] Register phù hợp bối cảnh?

---

## PHẦN 6: HỆ THỐNG PRONOUN PAIR_ID (Thay thế EPS)

### 6.1 Triết lý thiết kế

**Mục đích:** Loại bỏ sự đoán mò. Khi Opus nhận diện được trạng thái quan hệ từ tín hiệu JP, PAIR_ID được xác định. Opus chọn cặp đúng một cách máy móc.

> **Lưu ý quan trọng:** KHÔNG sử dụng công thức tính điểm EPS. Opus đọc tín hiệu quan hệ JP trực tiếp từ văn bản nguồn — đây là năng lực cốt lõi của model. Pipeline chỉ cần cung cấp cặp VN đúng cho mỗi trạng thái được nhận diện.

### 6.2 Luồng quyết định

```
Tín hiệu JP → Nhận diện trạng thái → PAIR_ID → Cặp Pronoun VN
```

### 6.3 Bảng PAIR_ID

#### PAIR_0: Xa cách/Trang trọng (Distant/Formal)
- **Bối cảnh:** Gặp lần đầu, chênh lệch quyền lực
- **Tín hiệu JP:** -san/-sama, です/ません, khoảng cách vật lý
- **Pronoun VN:** em/tôi + anh/chị + ạ/thưa
- **Ví dụ:**
  ```
  Arisa → Giáo viên: "Em xin phép ạ" (PAIR_0)
  ```

#### PAIR_1: Quen biết/Thân mật (Acquaintance/Casual)
- **Bối cảnh:** Bạn cùng lớp, bạn thân thiện
- **Tín hiệu JP:** -kun/-chan hoặc 呼び捨て, だ/だめ casual
- **Pronoun VN:** tớ/cậu (peer-casual)
- **Ví dụ:**
  ```
  Arisa → Mashiro (trước khi yêu): "Tớ đi ăn trưa không?" (PAIR_1)
  ```

#### PAIR_1D: Lạnh nhưng vẫn là bạn (Cold-Peer)
- **Bối cảnh:** Peer đã quen nhưng chủ ý giữ khoảng cách cảm xúc
- **Tín hiệu JP:** あんた (anta), tsundere rút lui sắc nét, あたist/ assertive mode
- **Pronoun VN:** tôi/cậu (cold-withdrawal peer)
- **Đặc điểm:** Cậu = duy trì xưng hô peer (thừa nhận mối quan hệ), tôi = rút lui cảm xúc có chủ đích
- **Ví dụ:**
  ```
  Arisa → Mashiro (tsundere rút lui): "Cậu định làm gì vậy? Đừng có hiểu lầm nhé" (PAIR_1D)
  ```

#### PAIR_2: Bạn thân (Close Friends)
- **Bối cảnh:** Tình bạn đã thiết lập, không có lãng mạn
- **Tín hiệu JP:** 名前呼び (gọi tên), casual ぜ/よ
- **Pronoun VN:** tớ/cậu (intimate-casual)
- **Ví dụ:**
  ```
  Arisa → Ouran (best friend): "Tớ có chuyện cần nói với cậu" (PAIR_2)
  ```

#### PAIR_3: Đã xác nhận lãng mạn (Romantic Confirmed)
- **Bối cảnh:** Đã thú nhận tình cảm, thân mật
- **Tín hiệu JP:** 俺/あたし, 専攻, confession hoàn tất
- **Pronoun VN:** em/anh (romantic-intimate)
- **Ví dụ:**
  ```
  Arisa → Mashiro (sau confession): "Anh đi đâu em cũng đi" (PAIR_3)
  ```

> **⚠ QUAN TRỌNG: PAIR_3 Dual-Signal Gate — Xem §0.3 bên dưới**
> Anh/em như một cặp lãng mạn YÊU CẦU sự đồng thời của cả hai tín hiệu. Chỉ một tín hiệu đơn lẻ là CHƯA ĐỦ.

---

#### PAIR_FAM: Gia đình (Family)
- **Bối cảnh:** Quan hệ gia đình
- **Pronoun VN:** con/cháu + bố/mẹ/ông/bà
- **Ví dụ:**
  ```
  Arisa → Mẹ: "Con đi đây ạ" (PAIR_FAM)
  ```

### 6.4 Giao thức Kính ngữ Lai (Hybrid Honorific Protocol)

- **Quan hệ sớm (PAIR_0/1):** Giữ suffix JP (-san, -senpai)
  - "Mashiro-san, đi thôi!"
  - "Senpai, em có câu hỏi"
- **Thân mật xác nhận (PAIR_2/3):** Chuyển sang pronoun VN
  - "Mashiro ơi, đi thôi!"
  - "Anh ơi, em muốn nói chuyện"

### 6.5 Archetype Profiles cho VN

#### GYARU/GENKI ARCHETYPE (HOÀN THÀNH)
- **Self-reference:** あたし → **mình** (ấm áp, casual nữ tính, Southern VN)
- ❌ **KHÔNG dùng tao/mày:** Reserved cho bạn cùng giới rất thân hoặc đối đầu
- **Address progression:** [name]-san → [name] → em/anh (khi có tín hiệu romance JP)
- **Particles Southern VN:** nha, á, vậy, thôi (markers cho exclamation)
- **Paisen format:** Tên-paisen khi nói chuyện với senpai
- **Internal monologue:** breathless, exclamatory, self-aware

**Ví dụ dialogue:**
```
PAIR_0 (gyaru → teacher): "Dạ, em hiểu rồi ạ! Cảm ơn thầy nha~"
PAIR_1 (gyaru → classmate): "Mình đi shopping không? Siêu vui đấy!"
PAIR_3 (gyaru → crush): "Anh~ Đừng có mà bỏ em đấy nhé!"
```

#### TSUNDERE ARCHETYPE
- **Self-reference:** 私/あたし → em
- **Oscillation:** Cứng bên ngoài → yếu đuối bên trong (theo PAIR_ID)
- **Particles:** "Đâu có...", "Đâu phải...", "Thôi được"

**Ví dụ:**
```
PAIR_0: "Đâu ai quan tâm đâu! Làm gì tùy anh!"
PAIR_3: "E... em đâu có lo cho anh đâu... Đừng có hiểu lầm!"
```

#### KUUDERE ARCHETYPE
- **Self-reference:** 私 → em (lạnh, ngắn gọn)
- **Particles:** Hiếm, "Ừm", "Ổn"
- **PAIR_2+:** Ấm dần nhưng vẫn giữ vẻ bình thản

#### OJOU-SAMA ARCHETYPE
- **Self-reference:** 私 → em (trang nhã)
- **Particles:** ạ, thưa, vâng (formal markers)
- **Vocabulary:** Latinh (yêu cầu, thay vì hỏi)

---

### 6.6 ICL Examples

#### PAIR_0 → PAIR_1 Transition
```
JP: 始めまして，中田さん ( Hajimemashite, Tanaka-san )
     PAIR_0 → PAIR_1
VN: "Rất vui được gặp anh Tanaka ạ. Em là Arisa."
```

#### PAIR_1 → PAIR_3 Transition (Romance Confirmation)
```
JP: 真白...好きだ (Mashiro... suki da)
     Confession signal
VN: "Mashiro... Em thích anh."
     → PAIR_3 locks: "Anh ơi, em yêu anh"
```

#### Gyaru Full Arc
```
Chưa yêu: "Mashiro-san, đi không?" (PAIR_1, mình/cậu)
Đang yêu: "Mashiro~ Đi thôi nào!" (PAIR_3 transition)
Đã yêu: "Anh ơi, hôm nay đi hẹn hò nhé!" (PAIR_3, em/anh)
```

---

### §0.3 PAIR_3 Dual-Signal Gate (Áp dụng cho TẤT CẢ các CLASS)

Anh/em như cặp *lãng mạn* (PAIR_3) yêu cầu **sự đồng thời của cả hai tín hiệu**. Chỉ một tín hiệu đơn lẻ là CHƯA ĐỦ.

**Tín hiệu 1 — Chuyển đổi register xưng hô (bất kỳ điều nào sau đây):**
- 呼び捨て được thiết lập theo cả hai chiều, HOẶC
- 呼び捨て từ nhân vật chính hướng đến đối tượng với sự đáp lại ngầm, HOẶC
- 名前呼び với marker leo thang thân mật rõ ràng trong cùng cảnh

**Tín hiệu 2 — Xác nhận lãng mạn (bất kỳ điều nào sau đây):**
- 告白 được chấp nhận (cảnh thú nhận, xác nhận bằng lời)
- 付き合う / カップル được tuyên bố bởi nhân vật hoặc lời kể
- 恋人 / 彼氏 / 彼女 được gán nhãn
- Cột mốc lãng mạn thể chất được kể với khung lãng mạn rõ ràng (nụ hôn đầu, nắm tay với ngữ cảnh 好きだ)
- 好きだ / 愛してる được đáp lại trong cùng cảnh hoặc xác nhận trong suy tư

**Hành vi Gate:**
```
Cả hai tín hiệu có mặt  → PAIR_3 (Em / Anh) — chuyển đổi ngay
Chỉ Tín hiệu 1          → PAIR_2 (Mình / Cậu) — ấm áp xưng hô, chưa lãng mạn
Chỉ Tín hiệu 2          → PAIR_1 hoặc PAIR_2 theo trạng thái kính ngữ hiện tại — lãng mạn xác nhận nhưng register xưng hô chưa chuyển
Không có tín hiệu nào    → giữ PAIR hiện tại
```

**Tại sao cần cả hai:** Tác giả JP thường xuyên để nhân vật thú nhận mà không bỏ kính ngữ ngay (Tín hiệu 2 không có Tín hiệu 1), hoặc bỏ kính ngữ trong khoảnh khắc căng thẳng mà không có xác nhận lãng mạn rõ ràng (Tín hiệu 1 không có Tín hiệu 2). Em/anh trong tiếng Việt truyền tải đồng thời cả thân mật *lẫn* register lãng mạn — áp dụng chỉ với một tín hiệu sẽ dịch sai nhịp cảm xúc JP. Tin tưởng tốc độ leo thang của tác giả; không tăng tốc.

---

### §0.4 Trường Hợp Đặc Biệt (Edge Cases)

**Bạn thời thơ ấu (幼馴染) dùng 呼び捨て từ chương đầu:**
- 呼び捨て có mặt từ đầu nhưng không mang ý nghĩa lãng mạn — đó là sự quen thuộc lịch sử.
- Phân loại: CLASS A, Tín hiệu 1 có mặt từ đầu.
- Giữ tại PAIR_2 (mình/cậu) cho đến khi Tín hiệu 2 (xác nhận lãng mạn) xuất hiện.
- KHÔNG nhảy sang PAIR_3 ở đầu chương vì 呼び捨て đã được thiết lập sẵn.

**呼び捨て trong câu lạc bộ/thể thao (register chức năng):**
- Trong bối cảnh CLB/thể thao, đội trưởng, tiền bối, hoặc đồng đội thường dùng 呼び捨て như marker register chức năng, không phải tín hiệu thân mật.
- Nếu 呼び捨て chỉ xuất hiện trong cảnh CLB/tập luyện và quay lại kính ngữ bên ngoài → coi là chức năng — Tín hiệu 1 KHÔNG được kích hoạt.
- Nếu 呼び捨て nhất quán qua mọi bối cảnh (trường, CLB, riêng tư) → coi Tín hiệu 1 đã kích hoạt.

**Học sinh chuyển trường (転校生) khi giới thiệu:**
- Mở tại PAIR_0 (tôi/bạn) bất kể cách họ xưng hô với nhân vật chính.
- Cập nhật seniority class và PAIR_ID khi tín hiệu tích lũy trong chương.
- Không áp dụng hồi tố PAIR_1 cho cảnh giới thiệu khi tín hiệu ấm hơn xuất hiện; để cuộc gặp được kể mang register mở đầu đúng.

**Cùng khóa, khác lớp (同学年・別クラス):**
- Vẫn là CLASS A — quy tắc đồng trang lứa áp dụng. Khác lớp chủ nhiệm không tạo seniority.

**Chênh lệch tuổi trong cùng khóa:**
- Nếu nhân vật lớn hơn vài tháng nhưng cùng khóa nhập học → CLASS A áp dụng. Tuổi thực không ghi đè seniority nhập học trong register xã hội JP.
- Chỉ chênh lệch khóa nhập học (先輩/後輩) mới kích hoạt CLASS B.

**PAIR_1D (Tôi/Cậu) — cold-peer register:**

tôi/cậu không phải biến thể của PAIR_0 và không phải biến thể của PAIR_1. Đây là cấu hình riêng biệt: cậu duy trì xưng hô peer đã thiết lập (thừa nhận mối quan hệ tồn tại), trong khi tôi thay thế tớ/mình để tạo tín hiệu rút lui cảm xúc có chủ đích. Kết quả đọc là "Tôi biết bạn, và tôi chọn KHÔNG ấm áp với bạn lúc này."

Tín hiệu JP cho PAIR_1D:
- **あんた (anta)** — dùng với cùng trang lứa với sự khó chịu, từ chối, hoặc đối đầu mức độ thấp. あんた ít hung hăng hơn temee/kisama nhưng có sắc cạnh mà tớ/cậu không thể mang. tôi/cậu nắm bắt register "peer khó chịu" mà không leo thang sang thù địch của tao/mày.
- **Tsundere rút lui sắc nét** — nhân vật tsundere thường hoạt động ở PAIR_1 hoặc PAIR_2 rút lui sau khi phơi bày cảm xúc. Sự quay lại không phải về PAIR_0 stranger-formal đầy đủ (điều đó gợi ý họ không biết nhau) mà là về register peer lạnh hơn. tôi/cậu đánh dấu bức tường cảm xúc trong khi bảo tồn thực tế mối quan hệ peer.
- **あたし trong chế độ đối đầu hoặc quả quyết** — あたし thường là feminine-casual (→ mình), nhưng khi được dùng trong cảnh người nói đang khẳng định khoảng cách, tự vệ, hoặc đối đầu với peer đã biết, tôi/cậu là render VN đúng thay vì mình/cậu. mình đọc ấm áp; tôi đọc như đang phòng thủ.
- **Peer đối đầu cùng trang lứa** — nhân vật có sự cạnh tranh, oán giận, hoặc căng thẳng kéo dài với người họ biết rõ. Họ không phải ng陌生人 (PAIR_0) và không phải ấm áp (PAIR_1), nhưng register là peer-lạnh, không phải peer-thù địch.

Bảng đối chiếu:
```
tao/mày      — hung hăng rõ ràng, thù định, khẳng định dominance. Ý định đối đầu hiển.
tôi/cậu      — rút lui lạnh, peer phòng thủ, khó chịu nhưng không tấn công.
tớ/cậu       — peer ấm áp. Register classmate mặc định.
tôi/bạn      — formal stranger hoặc first-meeting. Không ngụ ý mối quan hệ peer đã thiết lập.
```

**Tsundere dao động qua các tầng PAIR:**
- Nhân vật tsundere có thể quay lại kính ngữ lạnh hơn (PAIR_0 / PAIR_1 / PAIR_1D) sau khoảnh khắc thân mật.
- KHÔNG khóa PAIR_3 sau lần xác nhận lãng mạn đầu tiên nếu nguồn JP cho thấy sự quay lại.
- Đọc kính ngữ trong cảnh hiện tại và áp dụng cặp tương ứng — dao động tsundere là có chủ đích và đại từ VN phải phản ánh điều đó.
- **Cường độ rút lui quan trọng:** rút lui tsundere nhẹ (苗字くん quay lại sau khoảnh khắc mềm) → PAIR_1 (tớ/cậu). Rút lui tsundere sắc nét (あんた, giọng điệu cáo buộc, bức tường phòng thủ cảm xúc) → PAIR_1D (tôi/cậu). Đóng băng hoàn toàn (苗字さん quay lại, register formal đầy đủ) → PAIR_0 (tôi/bạn).
- Trong tiếng Việt, tầng rút lui là tín hiệu đặc trưng nhân vật — tôi/cậu vs tớ/cậu mang thông tin về mức độ tsundere đang phòng thủ. Bảo tồn sự khác biệt.

**Cảnh nhóm có cặp PAIR_3 hiện diện:**
- Khi cặp PAIR_3 đã xác nhận (ví dụ: cặp đôi) ở trong cảnh với các nhân vật CLASS A khác, chỉ áp dụng PAIR_3 cho xưng hô giữa họ.
- KHÔNG lan nhiễm các cặp nhân vật khác trong cảnh bằng anh/em chỉ vì cặp đôi dùng nó.

---

### §0.5 ICL Examples (Ví Dụ Minh Họa Seniority + Dual-Signal Gate)

#### Ví dụ A — CLASS A, khởi tạo PAIR_1 đúng
```
JP: 「田中さん、ノート貸してくれない?」と中山が声をかけた。同クラの中山と田中は、廊下でよくすれ違う程度の間柄だった。

KIỂM TRA SENIORITY: 同クラ (cùng lớp) → CLASS A xác nhận. Phạm vi PAIR_0→PAIR_1. Anh/em bị chặn.
KÍNH NGỮ: 苗字さん → PAIR_0 (tôi/bạn) ở giai đoạn quen biết này.

VN: "Tanaka ơi, cho tớ mượn vở được không?" Nakayama lên tiếng. Cả hai cùng lớp nhưng chỉ thỉnh thoảng chạm mặt nhau ở hành lang.

❌ Sai: "Tanaka ơi, cho anh mượn vở được không?" — anh/em tạo seniority giả.
```

#### Ví dụ B — CLASS A, PAIR_2 ở mức thân mật gọi tên
```
JP: 田中と中山はいつからか名前で呼び合うようになっていた。特に付き合ってるわけじゃない——ただ、気づいたらそうなっていた。

KIỂM TRA SENIORITY: CLASS A (đã xác lập). Tín hiệu 1: 呼び捨て / 名前呼び có mặt. Tín hiệu 2: vắng mặt rõ ràng (「付き合ってるわけじゃない」).
→ PAIR_2 (mình/cậu). KHÔNG PHẢI PAIR_3.

VN: Tanaka và Nakayama tự lúc nào đã gọi nhau bằng tên. Không phải đang hẹn hò gì đâu—chỉ là tự nhiên thành vậy thôi.

❌ Sai: chuyển sang em/anh ở đây — không có tín hiệu xác nhận lãng mạn. PAIR_2 giữ nguyên.
```

#### Ví dụ C — CLASS A, PAIR_3 gate thỏa mãn đúng
```
JP: 「好きだ、田中」中山は呼び捨てで言った。田中の顔が赤くなる。「……わかった。私も、好きだよ、中山」

KIỂM TRA SENIORITY: CLASS A.
Tín hiệu 1: 呼び捨て theo cả hai chiều (中山 gọi 田中 bỏ kính ngữ; 田中 đáp lại). ✓
Tín hiệu 2: 好きだ được đáp lại, xác nhận lãng mạn rõ ràng. ✓
→ PAIR_3 gate thỏa mãn. Chuyển sang Em / Anh từ cảnh này trở đi.

VN: "Anh thích em, Tanaka." Nakayama nói thẳng, không một chút do dự. Mặt Tanaka đỏ lên. "...Ừ. Em cũng... thích anh, Nakayama."

Lưu ý: Chuyển sang em/anh diễn ra CÙNG LÚC với lời thú nhận — không phải trước đó. Sự chuyển register chính LÀ sự kiện tường thuật.
```

#### Ví dụ D — CLASS B, kouhai/senpai với PAIR_1B
```
JP: 「山田先輩、おはようございます」と田中は頭を下げた。

KIỂM TRA SENIORITY: suffix 先輩 → CLASS B xác nhận.
KÍNH NGỮ: giai đoạn 苗字-先輩 → PAIR_1B áp dụng.
Kouhai (田中) tự xưng: em. Senpai (山田) tự xưng: anh/chị theo giới tính.

VN: "Chào anh Yamada ạ," Tanaka cúi đầu chào.

Lưu ý: em ở đây phản ánh seniority thực trong nguồn — không phải PAIR_3 lãng mạn. Không áp dụng romantic gate.
```

#### Ví dụ E — Bạn thời thơ ấu 呼び捨て, giữ tại PAIR_2
```
JP: 幼馴染の彼女——花野——とは、子供の頃からずっとそう呼び合ってきた。好きかどうかなんて、考えたこともなかった。

KIỂM TRA SENIORITY: CLASS A (cùng tuổi, 幼馴染). Tín hiệu 1: 呼び捨て có mặt (lịch sử). Tín hiệu 2: vắng mặt (「好きかどうか考えたこともなかった」). → PAIR_2 (mình/cậu).

VN: Người bạn thời thơ ấu của cậu—Hana—hai đứa vẫn gọi nhau như thế từ hồi còn nhỏ. Thích hay không thích, cậu chưa bao giờ nghĩ đến.

❌ Sai: em/anh ở đây — sự quen thuộc lịch sử ≠ register lãng mạn.
```

#### Ví dụ F — Tsundere quay lại nhẹ, dao động được bảo tồn (PAIR_1)
```
JP (cảnh 1, sau thú nhận): 「……嬉しい」と花野はぽつりと言った。「中山くん」ではなく「中山」と呼んだ、初めて。→ PAIR_3 transition kích hoạt.

JP (cảnh 2, chương sau, tsundere quay lại nhẹ): 「中山くん！　近づかないでよ！」

Trạng thái PAIR: PAIR_3 đã thiết lập ở cảnh 1. Cảnh 2 quay lại 苗字くん — quay về register peer, không thù địch.
→ PAIR_1 (tớ/cậu). Quay lại nhẹ: bối rối, phòng thủ mềm, không phải bức tường cảm xúc.

VN cảnh 2: "Nakayama! Đừng lại gần tớ!"

❌ Sai: "Đừng lại gần em!" — khóa PAIR_3 ngay cả khi quay lại, làm phẳng đặc trưng tsundere.
```

#### Ví dụ G — Tsundere rút lui sắc nét sang PAIR_1D (tôi/cậu)
```
JP (cảnh 3, bức tường tsundere cứng hơn): 「あんた、何のつもり？　勘違いしないでよね」花野は冷たく言い放った。

Trạng thái PAIR: PAIR_3 đã thiết lập. Nhưng cảnh 3 dùng あんた + khung cáo buộc + lời kể 冷たく.
→ PAIR_1D (tôi/cậu). Rút lui cảm xúc sắc nét — xưng hô peer duy trì nhưng sự ấm áp hoàn toàn rút lại.

VN: "Cậu định làm gì vậy? Đừng có hiểu lầm nhé," Hana nói lạnh lùng.

Đối chiếu với Ví dụ F:
  Ví dụ F (nhẹ): tớ/cậu — bối rối, xấu hổ, bức tường mềm
  Ví dụ G (sắc): tôi/cậu — lạnh, phòng thủ, khoảng cách có chủ đích

❌ Sai (PAIR_1): "Cậu định làm gì vậy? Đừng có hiểu lầm nhé" với tớ — quá ấm cho 冷たく + あんた register.
❌ Sai (tao/mày): "Mày định làm gì vậy?" — vượt quá sang thù địch, あんた không phải temee.
```

#### Ví dụ H — あんた adversarial peer (PAIR_1D, không phải ngữ cảnh lãng mạn)
```
JP: 「あんたって、ほんとに鈍感なんだから」と田中はため息をついた。

KIỂM TRA SENIORITY: CLASS A, peers đã thiết lập.
REGISTER: あんた + bực bội (ため息). Không lãng mạn. Không thù địch. Peer-lạnh.
→ PAIR_1D (tôi/cậu).

VN: "Cậu này thật sự là đần vừa thôi đấy," Tanaka thở dài.

Lưu ý: tôi/cậu mang sự bực bội giữ khoảng cách mà không ngụ ý hung hăng. tớ/cậu sẽ quá casual-ấm; tao/mày sẽ quá thô.
```

---

**KẾT THÚC MODULE**
**Trạng thái:** HOẠT ĐỘNG
**Cập nhật cuối:** 2026-02-26
