import json

with open('/Users/damminhthang/Documents/WORK/AI_MODULES/MTL_STUDIO/pipeline/config/literacy_techniques.json', 'r') as f:
    data = json.load(f)

corpus = data.get('real_world_jp_en_corpus', {})

# Metadata translations
metadata_translations = {
    "description": "Corpus chuyên nghiệp JP→EN dùng cho đo đạc chất lượng văn xuôi ICL. v3.0: 76 ví dụ thuộc 24 phân loại tâm trạng từ 8 nguồn được nhà xuất bản xác minh. Không nhiễm fan-TL.",
    "source": "Hibike! Euphonium [Yen Press] · Adachi & Shimamura [Seven Seas] · Tình Yêu Vô Hình Dưới Bầu Trời Đêm Quang [Yen Press] · 86—Eighty-Six [Yen Press] · Thám Tử Đã Chết Rồi [Yen Press] · Vòng Lặp Thứ 7 [Seven Seas] · Lớp Học Của Tinh Hoa [Seven Seas] · Không Có Cách Nào Tôi Sẽ Yêu Bạn! Trừ Khi [Seven Seas] · Cô Gái Tôi Cứu Trên Tàu [Yen Press]",
    "total_volumes": "Hibike Tập 1 · Adachi Tập 1,3 · Love Unseen Toàn Tập · 86 Tập 2,4 · Detective Dead Tập 1-4 · Loop7 Tập 1 · CotE Tập 1 · NfW Tập 1 · Train Tập 1",
    "generated": "2026-02-03"
}

# Free indirect discourse translations
fid_translations = {
    "description": "Các đoạn văn EN thể hiện nhận thức trực tiếp không có từ lọc (felt/saw/thought)",
    "instruction": "Sử dụng từ vựng cảm xúc của nhân vật để mô tả thực tại một cách trực tiếp, không qua trung gian",
    "pattern": "Nhận thức cảm xúc trực tiếp không có từ lọc (felt/saw/thought)"
}

# vn_instruction for each mood category
vn_instructions = {
    "literary_poetic": "Áp dụng kỹ thuật hình ảnh trực quan và chi tiết vật lý động. Sử dụng câu ngắn tạo nhịp căng thẳng, câu dài tạo không khí. Tránh tuyên bố trừu tượng về cảm xúc — để cảnh quan nói thay. Trong tiếng Việt: ưu tiên hình ảnh giác quan cụ thể (mùi, xúc giác, âm thanh), tránh 'cô ấy buồn' → dùng 'ánh mắt cô ấy như chìm xuống'.",
    "tension_suspense": "Chuyển lo âu nội tâm thành phản ứng sinh lý: tim đập nhanh, tay run, thời gian kéo dài. Kỹ thuật: 'cố gắng KHÔNG làm X' mạnh hơn 'cố không làm'. Trong tiếng Việt: dùng hình ảnh cơ thể ('chân như đóng đinh', 'tim như muốn nhảy ra') thay vì nói 'tôi lo lắng'.",
    "playful_banter": "Đối thoại trêu đùa nhẹ, thân mật thoải mái qua đùa cợt. Kỹ thuật: kết hợp hành động vật lý + so sánh + quan sát của người kể. Trong tiếng Việt: giữ giọng tự nhiên, tránh ngôn ngữ quá trang trọng trong đối thoại thân mật.",
    "wistful_bittersweet": "Nostalgia, buồn man mác dịu dàng, nhận thức về sự phù du. Kỹ thuật: lặp lại hành động (xem đồng hồ), kết thúc mở ('rồi sao nữa?'). Trong tiếng Việt: dùng ẩn dụ xúc giác (thời gian trượt qua tay như nước) để diễn đạt sự trôi qua.",
    "intimate_quiet_moments": "Gần gũi thể xác, nhạy cảm giác quan cao độ, im lặng như giao tiếp. Kỹ thuật: mô tả xúc giác tuần tự, chi tiết vi mô. Trong tiếng Việt: tập trung vào cảm giác cụ thể (ngón tay chạm vào tóc, hơi thở ấm) để xây dựng sự thân mật.",
    "deep_introspection": "Tự kiểm miễn cưỡng, mặc cảm thể hiện qua sự do dự, xấu hổ qua sự bất động. Không có từ lọc, không 'tôi nghĩ'. Trong tiếng Việt: dùng câu ngắn, không có lối thoát — nhân vật tự kết án chính mình.",
    "dramatized_romance": "Cảm xúc được thể hiện hoàn toàn qua hành vi, tránh né, hoặc hành động vi mô — không bao giờ tuyên bố. Trong tiếng Việt: dùng hành động cụ thể (quay đi, nín thở) thay lời thú nhận.",
    "endurance_as_devotion": "Tình yêu được thể hiện qua chi phí thể xác, vi tế, hoặc điều ước bất khả thi — không tuyên bố. Trong tiếng Việt: cho nhân vật chịu đựng đau đớn thể xác và ngay lập tức bỏ qua nó ('tôi không quan tâm, chẳng có gì quan trọng').",
    "kinetic_action_sequence": "Hành động mecha/quân sự chi tiết — nhịp cảm biến ngắn, vật lý như mối đe dọa. Kỹ thuật: thay đổi động từ liên tiếp (ngã, né, đỡ). Trong tiếng Việt: giữ câu ngắn dưới 8 từ khi hành động căng thẳng.",
    "mystery_deduction": "Logic suy luận của truyện trinh thám qua giọng nhân vật — suy luận qua im lặng, nhượng bộ chiến lược. Trong tiếng Việt: cho nhân vật đưa ra kết luận dựa trên chi tiết cụ thể, không giải thích rõ ràng.",
    "psychological_duel": "Đối đầu tâm trí — thuyết phục, cảm xúc, và logic là vũ khí. Trong tiếng Việt: giữ nhịp điệu căng thẳng, dùng câu ngắn cho các đòn đánh, câu dài cho sự do dự.",
    "grief_romance": "Tình yêu được thể hiện qua mất mát, hy sinh, và sứ mệnh kế thừa. Trong tiếng Việt: biểu hiện tang lễ và tình yêu qua hành động cấu trúc, không qua 'Tôi yêu bạn'.",
    "cunning_heroine_agency": "POV nữ chính kết hợp hành động thời gian thực với kiến thức chuyên môn nội tại. Trong tiếng Việt: cho nhân vật tính toán trong khi hành động — thể hiện kỹ năng qua quá trình suy nghĩ, không qua tuyên bố.",
    "retrospective_layering": "Kiến thức đa thời gian được dệt vào hành động hiện tại như nhận thức hiện tại, không phải hồi tưởng. Trong tiếng Việt: dùng thì tương lai từ hiện tại ('năm năm sau hắn sẽ xâm lược') thay vì 'trong kiếp trước cô ấy đã thấy'.",
    "earned_softening": "Nhân vật lạnh lùng được tiết lộ là ấm áp — nhưng sự tiết lộ được kiếm qua kiềm chế: một động từ, một nụ cười. Trong tiếng Việt: chỉ dùng một chi tiết nhỏ để phá vỡ sự cứng rắn, không tuyên bố.",
    "sibling_grief_payoff": "Cảm xúc gia đình được thể hiện qua hành động, không tuyên bố. Trong tiếng Việt: để nhân vật POV diễn giải cảm xúc mà nhân vật không thể nói ra.",
    "cold_intellectual_narrator": "Người kể chuyện mô tả bản thân với sự cô lập lâm sàng — báo cáo trạng thái nội tâm như dữ liệu bên ngoài. Trong tiếng Việt: giữ giọng phẳng, không thêm ấm áp. Chỉ cho phép những khoảnh khắc phá vỡ rất hiếm.",
    "sardonic_analysis_loop": "Người kể chuyện lạnh lùng áp dụng cách quan sát vào tình huống absurd hoặc tầm thường. Trong tiếng Việt: mô tả lâm sàng, đặt câu hỏi tu từ, trả lời bằng cách xác nhận sự phi lý.",
    "slapstick_interiority": "Hài kịch thể xác được mô tả qua nội tâm nhân vật thời gian thực. Trong tiếng Việt: mô tả thảm họa bằng máy móc — những gì cơ thể đang làm, không phải sự sốc cảm xúc.",
    "gl_intimate_crescendo": "Cảnh GL nơi sự phủ nhận của nhân vật dần thất bại dưới áp lực thân mật. Trong tiếng Việt: để cơ thể mâu thuẫn với sự phủ nhận, rồi trượt POV ở cao trào.",
    "comedic_escalation_chain": "Chuỗi nhanh mỗi nhịp tăng absurd hơn — thú nhận → tức giận → tự nhận xét → cáo buộc → né tránh → thành thật ngụy trang thành phủ nhận. Trong tiếng Việt: câu ngắn, ít dừng, không cho độc giả thở.",
    "observation_as_affection": "Nhân vật không thể hoặc không muốn đặt tên tình cảm lãng mạn thay bằng mô tả vật lý. Trong tiếng Việt: cho phép mô tả mất nhiều thời gian hơn cần thiết, chèn ẩn dụ rỉ một chút ấm áp.",
    "silent_channel_intimacy": "Sự thân mật qua kênh bị giới hạn — ghi chú, tin nhắn, bức vẽ. Trong tiếng Việt: để thông điệp viết ngắn (3-5 từ), để người gửi chuẩn bị, để người nhận diễn giải phụ đề cảm xúc.",
    "genre_aware_epilogue": "Kết chương nơi người kể chuyện bước vào prolepsis — nói từ góc nhìn sau về điều họ chưa biết. Trong tiếng Việt: một dòng, thì tương lai, tự giễu, cờ thể loại để xác nhận điều gì đó đang đến."
}

# Mood description translations
mood_desc_translations = {
    "literary_poetic": "Hình ảnh trực quan, chi tiết vật lý động, trọng lượng cảm xúc được truyền tải qua quan sát giác quan thay vì tuyên bố trừu tượng. Câu ngắn dồn dập tạo căng thẳng; câu dài tạo không khí. Lý tưởng cho cảnh kịch tính, giới thiệu nhân vật, chuyển cảnh.",
    "tension_suspense": "Lo âu nội tâm, phản ứng sinh lý với căng thẳng, hiệu ứng giãn thời gian, nỗi sợ chờ đợi. Lý tưởng cho căng thẳng lãng mạn, cảnh trước thú nhận, lo xã hội, khoảnh khắc chờ đợi.",
    "playful_banter": "Đối thoại trêu đùa, châm biếm nhẹ, sự thân mật thoải mái qua đùa cợt. Lý tưởng cho mối quan hệ đã thiết lập, giải trợ, tán tỉnh không thú nhận.",
    "wistful_bittersweet": "Nostalgia, buồn man mác dịu dàng, nhận thức về sự phù du, chấp nhận cảm xúc mềm mại. Lý tưởng cho lời từ biệt, chuyển mùa, tình cảm không được đáp lại, khoảnh khắc suy tư.",
    "intimate_quiet_moments": "Sự gần gũi thể xác, nhạy cảm giác quan cao độ, im lặng như giao tiếp, thân mật qua chạm. Lý tưởng cho cao trào lãng mạn, cảnh an ủi, sự vulnerable.",
    "deep_introspection": "Tự kiểm miễn cưỡng, mặc cảm được thể hiện qua sự do dự, xấu hổ qua sự bất động. Nhân vật nhận ra điều không hay về bản thân và không né tránh. Lý tưởng cho xung đột nội tâm, khoảnh khắc hèn nhát, tự ghét, khoảng cách giữa ta là ai và ta muốn là ai.",
    "dramatized_romance": "Cảm xúc được truyền tải hoàn toàn qua hành vi, né tránh, hoặc hành động vi mô — không bao giờ được tuyên bố. Sự hấp dẫn được thể hiện qua kiềm chế: nhìn đi chỗ khác, thở có kiểm soát, cố tình không chạm. Lý tưởng cho lãng mạn chậm, nhận thức đầu tiên về cảm xúc, cảnh nơi nhân vật từ chối thừa nhận điều họ cảm thấy.",
    "endurance_as_devotion": "Tình yêu được thể hiện qua chi phí thể xác, vi tế, hoặc điều ước bất khả thi — không bao giờ được tuyên bố. Nhân vật chịu đựng, hy sinh, hoặc thực hiện một hành động quan tâm nhỏ, và trọng lượng cảm xúc được mang hoàn toàn bởi cường độ không cân xứng của hành động. Lý tưởng cho cảnh khủng hoảng cao trào, khoảnh khắc nhân vật nhận ra cảm xúc sâu đến mức nào, hoặc cảnh yên tĩnh nơi một cử chỉ nhỏ tiết lộ tất cả.",
    "kinetic_action_sequence": "Chuỗi hành động mecha/quân sự chi tiết — nhịp cảm biến ngắn, vật lý được mô tả như mối đe dọa, chi phí thể xác như bằng chứng sống. Dùng cho bản dịch hành động đòi hỏi sự trực tiếp nội tạng mà không làm chậm đà cảnh.",
    "mystery_deduction": "Logic suy luận của truyện trinh thám được thể hiện qua giọng nhân vật — suy luận qua im lặng, nhượng bộ chiến lược trong đối đầu phản diện. Lý tưởng cho cảnh trinh thám, đối đầu tâm lý, khoảnh khắc suy luận.",
    "psychological_duel": "Đối đầu tâm trí nơi thuyết phục, cảm xúc, và logic là vũ khí — số phận bất khả kháng cứ vs hành động. Lý tưởng cho cảnh đối đầu căng thẳng, thương lượng cao, xung đột chiến lược.",
    "grief_romance": "Tình yêu được thể hiện qua mất mát, hy sinh, và sứ mệnh kế thừa — tình yêu chỉ có thể được nói qua cái chết hoặc hành động. Lý tưởng cho cảnh tang lễ, bi kịch, hy sinh anh hùng.",
    "cunning_heroine_agency": "POV nữ chính kết hợp hành động thời gian thực với kiến thức chuyên môn nội tại. Năng lực được thể hiện qua tính toán giữa chừng hành động qua FID in nghiêng — cơ thể quản lý nhiệm vụ trong khi tâm trí đánh giá nó. Không bao giờ nói nhân vật là giỏi; cho thấy tính toán cô ấy chạy trong khi làm điều đó.",
    "retrospective_layering": "Kiến thức đa kiếp hoặc đa thời gian được dệt vào hành động hiện tại như nhận thức hiện tại, không phải hồi tưởng hay khối giải thích. Kinh nghiệm quá khứ xuất hiện như sự thật thời gian thực — 'hắn sẽ xâm lược' không phải 'trong kiếp trước cô ấy đã học hắn sẽ xâm lược'.",
    "earned_softening": "Nhân vật lạnh lùng, đe dọa, hoặc thù địch được tiết lộ là ấm áp — nhưng sự tiết lộ được kiếm qua kiềm chế: một động từ, một nụ cười, một ký ức, không phải tuyên bố. Kỹ thuật phụ thuộc vào đầu tư trước vào sự cứng rắn của nhân vật; vết nứt phải cảm thấy như bất ngờ mà độc giả ngay lập tức nhận ra là tất yếu.",
    "sibling_grief_payoff": "Cảm xúc gia đình được thể hiện qua hành động thay vì tuyên bố. Bạo lực, kiềm chế thể xác, hoặc can thiệp đứng thay cho tình yêu không thể nói ra. Nhân vật lạnh giận tiết lộ sự quan tâm; nhân vật ấm áp phản ứng bối rối thay vì dịu dàng.",
    "cold_intellectual_narrator": "Người kể chuyện mô tả bản thân với sự cô lập lâm sàng — báo cáo trạng thái nội tâm như dữ liệu bên ngoài, không biểu hiện xấu hổ cho sự không hành động chiến lược, phân tích sự tốt của người khác từ vị trí không tham gia có chủ đích. Sự vắng mặt phản ứng cảm xúc LÀ sự đặc trưng hóa.",
    "sardonic_analysis_loop": "Người kể chuyện lạnh hoặc phân tích áp dụng cách quan sát của họ vào tình huống absurd hoặc tầm thường, tạo hài kịch qua sự không tương xứng giữa trọng lượng của phân tích và sự tầm thường của chủ đề. Vòng lặp leo thang bằng cách trả lời câu hỏi của chính nó với kết luận không đủ ngày càng tăng.",
    "slapstick_interiority": "Hài kịch thể xác được mô tả qua nội tâm nhân vật thời gian thực. Hài kịch đến từ khoảng cách giữa mức độ nghiêm trọng của tình huống (nguy hiểm thực sự) và giọng của bình luận nội tâm (thanh xuân bình thường, khung văn hóa đại chúng, tự nhận thức absurd).",
    "gl_intimate_crescendo": "Cảnh GL nơi sự phủ nhận của nhân vật chính dần thất bại dưới áp lực thân mật thể xác, thú nhận chân thành, hoặc sự chắc chắn tuyệt đối của nhân vật khác. Cường độ hoạt động theo lớp: cơ thể phản ứng trước, rồi bình luận nội tâm của người kể mâu thuẫn chính nó, rồi trượt POV hoặc vỡ mặt nạ xác nhận điều mà sự phủ nhận đã bảo vệ.",
    "comedic_escalation_chain": "Chuỗi nhanh mỗi nhịp tăng absurd hơn của cái trước — thú nhận → tức giận → tự nhận xét → cáo buộc → né tránh → thành thật ngụy trang thành phủ nhận. Hoạt động qua đà: câu ngắn, ít dừng, không cho độc giả thở cho đến câu kết cuối cùng.",
    "observation_as_affection": "Người kể chuyện không thể hoặc không muốn đặt tên tình cảm lãng mạn thay bằng mô tả vật lý cho tuyên bố cảm xúc. Việc kiểm kê vẻ ngoài của nhân vật khác — được truyền tải với độ chính xác và thời gian dành — LÀ sự thú nhận.",
    "silent_channel_intimacy": "Sự thân mật được thực hiện qua kênh bị giới hạn — ghi chú viết, tin nhắn, bức vẽ — nơi giới hạn của kênh buộc ngắn gọn và chân thành. Điều không thể nói lại (được viết) ràng buộc hơn lời nói.",
    "genre_aware_epilogue": "Kết chương nơi người kể chuyện bước vào prolepsis ngắn gọn — nói từ góc nhìn muộn hơn về điều họ chưa biết hoặc hiểu tại thời điểm hiện tại của câu chuyện. Hoạt động như tín hiệu thể loại (đây là lãng mạn; chú ý nhân vật này) và như sự mỉa mai nhân vật (tự đánh giá của người kể đã sai ngay với độc giả)."
}

# Why premium translations
why_premium_translations = {
    "hibike_001": '"Crescent-shaped marks into the sweat-sticky palms" là chi tiết xúc giác chính xác, không phải "cô ấy lo lắng." Đoạn văn di chuyển từ đám đông đến nhân vật chính đến da, thu hẹp tiêu điểm như zoom máy ảnh.',
    "hibike_002": '"Hesitantly beginning to peek out" trao quyền cho nụ nở hoa. Dấu chấm phẩy xoay từ красота đến thờ ơ — đối lập LÀ tuyên bố cảm xúc. Không ai nói cô đơn. Cảnh nói điều đó.',
    "hibike_003": '"Invisible membrane" đóng đoạn văn như chìa khóa xoay trong ổ khóa. Âm thanh từ bên ngoài (đội bóng chày) làm sâu sắc thêm sự cô lập của họ qua đối lập: thế giới tiếp tục; khoảnh khắc của họ bị đình chỉ.',
    "hibike_004": '"Carved itself with unpleasant clarity" — giọng nói là một lưỡi dao. Ký ức quay lại qua chi tiết vật lý cụ thể (đôi mắt), không phải mặc cảm trừu tượng. "Chạy khỏa mùa hè đó" — mùa trở thành vết thương, không phải người.',
    "adachi_001": '"Tying myself in knots" là thành ngữ và hình ảnh. Neo lo âu trừu tượng vào chi tiết cụ thể (quên sự khiêm tốn). Tránh "tôi lo lắng" kể.',
    "adachi_002": '"Gnawed and gnawed" truyền tải việc kiểm tra ám ảnh qua lặp lại hành động. "Gave in" cho thấy giải quyết xung đột nội tâm. Nhịp chặt.',
    "adachi_003": '"Focused all my energy into NOT doing X" mạnh hơn "cố không nhìn." Làm cho sự tránh né chủ động, không bị động.',
    "adachi_004": 'Nắm bắt lo âu qua chuyển dịch nhận thức thời gian (chậm → nhanh). "Dizzying" cầu nối ẩn dụ với cảm giác leo thang đến sợ hãi cụ thể (ngất xỉu).',
    "loveunseen_008": '"Nailed" là động và bạo lực — thứ gì đó bên ngoài đã cố định anh ta, không phải lựa chọn. Khung bị động ("seemed to") thêm kinh hoàng: anh ta là chủ thể, không phải tác nhân. Khác với kiềm chế chủ động (adachi_003) — đây là tắt máy không tự nguyện dưới cực độ cảm xúc.',
    "adachi_005": 'Đối thoại + hành động vật + so sánh của người kể tạo cảnh đầy đủ. So sánh ("như đứa trẻ") thêm tình cảm mà không nói "tôi thấy dễ thương".',
    "adachi_006": '"Self-esteem getting ready to plummet" là cường điệu hài hước. Dùng cấu trúc động từ chủ động (tự trọng như tác nhân) để tạo hài hước.',
    "adachi_007": '"Dozen or so times" lượng hóa sự khó xử mà không nghĩ đen. "Silent What? looks" là show-dont-tell cho sự bối rối.',
    "adachi_008": 'Lặp lại xem đồng hồ để cho thấy nhận thức ám ảnh. "Và rồi sao?" để câu hỏi treo, phản ánh sự không chắc chắn của nhân vật.',
    "adachi_009": 'Cảm giác vật lý (tóc trượt) trở thành ẩn dụ cho sự phù du. "Evaporated" nâng hành động đơn giản lên thành hình ảnh buồn man mác.',
    "adachi_010": 'Kích thích bên ngoài → ẩn dụ nội tâm → kiểm tra tự giễu thực tế. "Terminal case" hài hước nhưng cũng tiết lộ chiều sâu cảm xúc.',
    "adachi_011": 'Lạnh thể xác phản chiếu khoảng cách cảm xúc. "Faintest outline" là thơ trực quan. Câu dài phù hợp trạng thái suy tư.',
    "adachi_012": 'Nắm bắt hai trải nghiệm vật lý đồng thời (ticklish vs buồn ngủ). "Blinking hard" là hành động cụ thể cho sự mệt mỏi trừu tượng.',
    "adachi_013": 'Cùng bàn tay cảm thấy khác tùy bối cảnh. Câu hỏi triết học theo quan sát. Cho thấy động lực quan hệ qua cảm giác thể xác.',
    "adachi_014": '"Gums throb" là chi tiết cụ thể bất thường khiến cảm xúc trở nên trực quan. Mô tả xúc giác tuần tự xây dựng sự thân mật từ từ.',
    "loveunseen_001": 'Câu không có lối thoát. "Noticing" và "being upset" bị lên án đồng thời — anh ta ghét việc nhận th ghét việc nó làmấy VÀ anh ta buồn. 14 từ chứa bẫy tâm lý đầy đủ. Không từ lọc, không "tôi nghĩ," không làm dịu. Show-dont-tell thuần túy của nhân vật không thể tha thứ cho bản thân.',
    "loveunseen_002": '"Waited for someone else" là hành động — hoặc không-hành động. Xấu hổ đến ngay lập tức không có đệm. "Such a lowlife" là tự kết án thẳng thắn, không văn chương, khiến nó trung thực hơn. Anh ta không văn chương hóa thất bại của mình. Anh ta đặt tên nó.',
    "loveunseen_003": 'Từ "excuse" đang làm công việc lớn — anh ta đã phân loại lý luận của mình là một lời biện minh trước khi kết thúc câu. Đau thể xác xác nhận nó. 10 từ. Nhân vật đã tự kết án hoàn toàn trước khi độc giả có thể.',
    "loveunseen_004": '"Transparent" là từ quan trọng — anh ta có thể thấy cô rõ ràng nhưng không thể chạm đến. Bức tường không đục (thờ ơ) mà trong suốt (khát khao không có quyền truy cập). 9 từ chứa toàn bộ cung trọng lượng cảm xúc của tiểu thuyết.',
    "loveunseen_011": '"Gave up on giving up" ngữ pháp đệ quy và cảm xúc tinh khiết — phủ định kép không vụng về, nó chính xác. Anh ta cố gắng tách ra. Anh ta thất bại. Thất bại đó là khởi đầu. 11 từ đặt tên điểm bản lề chính xác của toàn bộ mối quan hệ.',
    "loveunseen_005": 'Từ xoay là "though" — nó tách phản ứng không tự nguyện khỏi phản ứng được chọn. "Turned away" là toàn bộ lãng mạn cô đọng trong một hành động. Anh ta không nói "tôi thích nụ cười của cô." Anh ta quay đi từ nó. Độc giả hiểu mọi thứ nhân vật từ chối.',
    "loveunseen_006": '"Held my own breath... trying not to breathe on her" — sự kiềm chế của anh ta LÀ sự dịu dàng. Anh ta đang bảo vệ cô khỏi sự hiện diện của chính mình. Đây lãng mạn hơn bất kỳ tuyên bố nào vì nó cho thấy một người đàn ông cố chiếm ít không gian hơn vì sự kính trọng. Mong muốn được thể hiện như sự tự phủ nhận.',
    "loveunseen_007": 'Cấu trúc như ngạc nhiên sau đó nhận ra sau đó tàn phá. Anh ta nhận ra cái đẹp, sau đó nhận ra cô không thể chia sẻ — khoảng đó LÀ lãng mạn. Câu hỏi cuối cùng không phải tu từ; đó là khoảnh khắc đầu tiên anh ta thực sự nhìn thấy tình huống của cô. Trăng trở thành mọi thứ anh ta muốn cho cô mà anh ta không thể.',
    "loveunseen_009": 'Cô không buộc tội anh ta lừa dối — cô đang nói với anh ta cô biết anh ta yêu cô, bằng ngôn ngữ cho phép cả hai sống sót qua sự thú nhận. "Kind lies" tái định nghĩa không trung thực như sự tận tâm. Dấu hỏi không phải câu hỏi. Đó là tuyên bố với khả năng chối bỏ được xây dựng trong đó. Cách sử dụng tinh vi nhất của đối thoại-như-thú-nhận trong corpus.',
    "loveunseen_010": 'Hơi thở đầu tiên thất bại — đó là điều hơi thở thứ hai cho chúng ta biết. Anh ta không bao giờ nói "tôi gần như khóc." Sự lặp lại ("then an even deeper one") là manh mối. "In an effort to hold back" xác nhận anh ta ở bờ vực mà không xác nhận liệu anh ta có thành công. Độc giả hoàn thành bức tranh. Show-dont-tell hoàn hảo cho nhân vật từ chối gục ngã.',
    "loveunseen_012": 'Đau khổ vật lý được đặt tên ("blood," "aching") và ngay lập tức bị bỏ qua ("none of it mattered"). Sự bỏ qua LÀ tuyên bố. Anh ta không nói "tôi yêu cô." Anh ta nói tên cô và "càng sớm càng tốt." Sự khẩn cấp ở trong ngữ pháp — không mệnh đề phụ, không phản ánh. Chỉ chuyển động về phía trước. Dùng khi tình yêu của nhân vật phải được thể hiện qua hành động trong cực độ thay vì ngôn ngữ cảm xúc.',
    "loveunseen_013": 'Hành động nhỏ phi thường (đặt giấy). Lời cảm ơn là hai từ ("Cảm ơn"). Phản ứng của anh ta là hân hoan quá mãnh liệt anh ta mất kiểm soát bản thân. Tải trọng cảm xúc không cân xứng là dấu hiệu của giai đoạn đầu của tình yêu — mọi mảnh chú ý trở nên to lớn. Dùng khi nhân vật chưa thể thú nhận cảm xúc nhưng niềm vui của họ ở những điều nhỏ nhặt phản bội họ.',
    "loveunseen_014": 'Ba câu: thời gian pháo hoa → tuổi thọ → xác nhận từ trái tim. Nén cấu trúc hoàn hảo: đối tượng cụ thể mở ra suy nghĩ, điều ước bất khả thi theo sau, "from the bottom of my heart" đóng nó không có mỉa mai. Anh ta không nói "tôi yêu cô, đừng chết." Anh ta nói nó qua pháo hoa đang cháy trong bóng tối. Điều ước LÀ sự thú nhận.',
    "eighty6_001": 'Mối đe dọa được chứng minh bởi một mảnh kính trên sàn — không phải đau đớn của nhân vật chính, không phải đối thoại cảnh báo, không phải cắt máy quay. Radar nói không có gì; kính nói tất cả. "Một giác quan tách biệt khỏi năm giác quan thông thường" thiết lập radar siêu nhiên của nhân vật mà không giải thích quá mức.',
    "eighty6_002": 'Cấu trúc câu phản chiếu sự lệch hướng: mệnh đề phụ dài thiết lập khả năng ("cắt như bơ") đâm vào xoay nghịch ("nhưng trong khoảnh khắc tiếp theo") rồi va vào mệnh đề đối lập. Vật lý cảm thấy được sống vì thuật ngữ cụ thể (rung động, vector, thân máy bay) nhưng cảnh kết thúc bằng âm thanh thuần túy.',
    "eighty6_003": 'Sự chuyển đổi từ thuật ngữ kỹ thuật sang trực giác — từ "tần số đối ứng" đến "thứ gì đó mùi như thứ gì đó chết" — đánh dấu khoảnh khắc Shin ngừng chiến đấu bằng phân tích và bắt đầu chiến đấu bằng trực giác.',
    "eighty6_004": 'Giọng khàn, cổ họng khô, canopy không mở trong nhiều giờ — đây là những chi phí chiến thắng duy nhất được phép. Không tự khen ngợi qua hành động; chỉ qua những gì cơ thể không làm được.',
    "eighty6_005": 'Câu ngắn 4 từ kết thúc bởi từ sai chính tả — giọng nói mệt mỏi của ai đó quá mệt để nói đúng. Đây là FID hoạt động như kết thúc cảnh: không có gì cần nói thêm, chỉ có thực tế của sự sống sót.',
    "detective_001": '"Cái chết của Takachiho-kun" — sở hữu cách tạo khoảng cách lạnh lùng. "Cậu ấy chết rồi" sẽ gần hơn nhưng vẫn giữ sự kiểm soát. Nhân vật phân tích cách chết mà không đau đớn.',
    "detective_002": 'Im lặng là bằng chứng — anh ta không cần nói. "Cứ thế" được lặp lại như tiếng vọng của sự mất mát. Dùng cho cảnh nơi sự hiện diện của người vắng mặt mạnh hơn lời nói.',
    "detective_003": '"Đau dữ dội" là từ y học cho đau. "Đau như bị dao cắt" sẽ là văn chương. Sự lựa chọn từ lâm sàng cho thấy nhân vật đang phân tích đau thay vì cảm nhận nó.',
    "detective_004": 'Câu hỏi tu từ trở thành lời thú nhận. "Anh có muốn tôi giết anh không?" không phải câu hỏi — đó là lời thú nhận rằng cả hai đều biết câu trả lời.',
    "detective_005": '"Tôi không có gì để nói" trong khi tất cả mọi thứ đang diễn ra xung quanh — sự tĩnh lặng là tuyên bố mạnh nhất. Dùng cho khoảnh khắc nhân vật chọn không nói thay vì không thể nói.',
    "loop7_010": '"Đây là số phận" vs "Tôi sẽ thay đổi số phận" — sự đối lập xác định xung đột. Người lạnh lùng chấp nhận; người ấm áp chiến đấu.',
    "loop7_011": '"Nụ cười đó" được lặp lại như tiếng vọng — mỗi lần mang một ý nghĩa khác. Lần đầu = chiến lược. Lần hai = đau. Lần ba = chấp nhận.',
    "loop7_012": 'Câu dài với nhiều mệnh đề phụ cho thấy sự kiểm soát trong khi nội tâm đang hỗn loạn. Dùng cho cảnh nơi nhân vật phải giữ bình tĩnh trong khi bên trong đang sục sôi.',
    "loop7_013": '"Tôi không có thời gian cho những thứ không quan trọng" — sự từ chối lịch sự là sự từ chối rõ ràng nhất. Không nói "không" nhưng ý nghĩa là không.',
    "detective_006": 'Vết sẹo trở thành ẩn dụ cho ký ức — không phải vết thương vật lý mà là dấu ấn tâm lý. "Mỗi khi nhìn thấy nó, tôi nhớ lại" — hành động nhìn trở thành hồi tưởng.',
    "detective_007": '"Cô ấy mỉm cười" — nụ cười như mặt nạ. Người đàn ông biết cô đang giấu điều gì đó nhưng chọn không đào sâu. Sự tôn trọng trở thành sự thân mật.',
    "detective_008": '"Tôi sẽ không khóc" — quyết định trở thành hành động. Anh ta không khóc, nhưng sự kiềm chế đó là tuyên bố tình yêu mạnh nhất.',
    "detective_009": '"Được cứu bởi một người xa lạ" — sự ngạc nhiên trở thành sự thay đổi. Anh ta không biết ai cứu mình nhưng quyết định tìm kiếm — đó là bắt đầu của tình yêu.',
    "loop7_001": '"Trọng lượng phân bố đều trên mu bàn chân" là danh sách kiểm tra vật lý được giao trong khi ngã — không phải hồi tưởng, không phải lời bình của người kể, mà là hướng dẫn trực tiếp chạy song song với hành động. Độc giả học nhân vật được huấn luyện trong khi xem cô tự huấn luyện.',
    "loop7_002": 'Năng lực của Rishe được truyền tải hoàn toàn qua sự sốc của Tully — chúng ta thấy nó qua mắt chuyên gia, khiến nó có trọng lượng gấp đôi.',
    "loop7_003": 'Bánh quy không đụng đang làm việc cảm xúc mà người kể không bao giờ nói: cô ấy quá buồn để ăn. Show-dont-tell qua đạo cụ.',
    "loop7_004": '"Năm năm sau, Arnold Hein sẽ xâm lược Hermity" được viết bằng thì tương lai từ hiện tại, không phải "trong những kiếp trước cô ấy đã thấy." Độc giả nhận tin tình báo như sự thật hoạt động, không phải tiểu sử.',
    "loop7_005": 'Trích dẫn Tully nhúng vào giữa cảnh là ký ức — nhưng chúng đến với khung zero: không "cô ấy nhớ anh ấy nói," không in nghiêng, không ngắt đoạn.',
    "loop7_006": '"A rare chuckle" — từ "rare" mang toàn bộ lịch sử sự nghiêm khắc của người đàn ông này trong hai âm tiết. Phản ứng kinh ngạc của người hầu nhân đôi tín hiệu qua một nhân chứng.',
    "loop7_007": '"Of course I do" — bốn từ làm việc của một đoạn văn backstory. Arnold chưa bao giờ thể hiện sự ấm áp công khai, nên sự thú nhận này của ký ức tương đương với một tuyên bố.',
    "loop7_008": 'Smack! — dấu ngắt trước và sau một onomatopoeia duy nhất làm nó trở thành khoảnh khắc lớn nhất chương. Đối thoại của Arnold vẫn lạnh ("Loại ngốc nào...") nhưng giọng hét là một vết nứt.',
    "loop7_009": '"Đôi mắt — cùng đôi mắt đó" là lựa chọn của dịch giả để nhấn mạnh anh em chia sẻ khuôn mặt: sự tổn thương của Theodore LÀ của Arnold, phản chiếu.',
    "cote_001": 'Ayanokouji nhận ra và đặt tên lòng can của cô gái ("no simple feat") và vẫn không nhúc nhích. Không có xung đột nội tâm, không "Tôi muốn nhưng không thể."',
    "cote_002": 'Vòng lặp triết học ("Tình bạn là gì?") là hài kịch qua trì hoãn — càng phân tích lâu, càng nhiều bạn bè người khác có được.',
    "cote_003": 'Giới thiệu là bài học về sự đơn điệu chiến lược — "interested in just about anything" và "at least a few" friends là cố ý chung chung.',
    "cote_004": '"That certainly sounded like something Kouenji would say" — phản ứng của Ayanokouji với tự yêu bản thân spectacular là xác nhận nó nghe có vẻ đúng nhân vật. Không sốc, không phán xét, chỉ phân loại.',
    "cote_005": '"He was trying to get the Professor to buy it and had shamelessly increased the price" — người kể nhận ra sự tăng giá và báo cáo trung lập, không bình luận về sự táo bạo.',
    "nfw_001": '"Oh no! Oh no!" — lặp lại exclamation là phiên bản hoảng sợ teen chân thực nhất trong corpus. "Was I legit falling off the roof?" — "legit" là slang làm sụp đổ tính trang trọng.',
    "nfw_002": '"I flopped around it in a u-shape" — độ chính xác cơ học ("u-shape") hài hơn bất kỳ cường điệu nào vì nó chính xác.',
    "nfw_003": '"Tense up, yet at the same time completely relaxing and satisfying" — hai phản ứng vật lý mâu thuẫn trong một câu báo hiệu sự hấp dẫn mà người kể không đặt tên. Dòng cuối là kỳ tự POV: người kể đã trượt vào POV của Mai mà không có thông báo.',
    "nfw_004": '"How?! You don\'t even have a dick!" — exclamation là vụ nổ hài hước hoạt động vì nó là phản ứng trực tiếp nhất có thể; não của người kể đã vượt qua mọi bộ lọc xã hội.',
    "nfw_005": '"My face turned an unnecessarily bright shade of red" — từ "unnecessarily" là phán xét của chính Renako về sự đỏ mặt của mình: cô ấy biết nó không hợp lý và không thể dừng lại.',
    "nfw_006": '"Too well!" — mâu thuẫn (thắng quá thuyết phục là vấn đề) đặt logic hài. "Bumping heads with the freaking Tokyo Skytree!" — cường điệu là Renako tìm đối tượng lớn nhất có thể để so sánh.',
    "nfw_007": '"Housekeeping" là ngôn ngữ kinh doanh trang trọng được triển khai trong cảnh đàm phán mối quan hệ GL — sự không khớp register là tiếng cười trước khi Mai thậm chí trả lời.',
    "train_001": 'Đoạn văn liệt kê: da, má, môi, lông mi, chân, váy, tay, ngón tay, móng tay — mỗi chi tiết được thêm theo cách ai đó thêm vào danh sách họ không muốn dừng.',
    "train_002": '"Yeah," I muttered, and she smiled." — giao dịch xuất hiện hoàn thành: câu hỏi được hỏi, trả lời, nụ cười nhận được. Dòng tiếp theo làm nổ tung nó: "Actually, I wasn\'t getting it at all."',
    "train_003": 'Ghi chú của Fushimi — ba từ, "Cảm ơn đã giúp tôi" — đến trước bất kỳ trao đổi lời nói nào. Lời cảm ơn viết là vĩnh viễn theo cách lời nói không.',
    "train_004": '"She was trying to erase the cat\'s speech bubble as I said that, and she stopped right in her tracks" — sự xóa là manh mối: điều gì đó trong phản ứng của anh ta làm cô ấy dừng lại vì nó gần với ý nghĩa thực hơn "toán học."',
    "train_005": '"Completely average dude like me" ngay lập tức bị giảm sức bởi chương vừa xảy ra: "average dude" này đã can thiệp vào vụ sờ mó trên tàu với chi phí cá nhân.'
}

# Build output structure
output = {
    "real_world_jp_en_corpus": {
        "description": metadata_translations["description"],
        "source": metadata_translations["source"],
        "total_volumes": metadata_translations["total_volumes"],
        "generated": metadata_translations["generated"],
        "free_indirect_discourse_examples": {
            "description": fid_translations["description"],
            "instruction": fid_translations["instruction"],
            "pattern": fid_translations["pattern"],
            "examples": corpus["free_indirect_discourse_examples"]["examples"]
        }
    }
}

# Professional prose translations
prose = corpus.get('professional_prose_icl_examples', {})
moods = prose.get('examples_by_mood', {})

output_prose = {
    "version": prose.get("version"),
    "description": "Ví dụ văn xuôi cao cấp được lấy độc quyền từ bản dịch nhà xuất bản được cấp phép. v3.0 thêm 26 ví dụ mới thuộc 12 phân loại tâm trạng mới từ Vòng Lặp Thứ 7 [Seven Seas], Lớp Học Của Tinh Hoa [Seven Seas], Không Có Cách Nào Tôi Sẽ Yêu Bạn! Trừ Khi [Seven Seas], và Cô Gái Tôi Cứu Trên Tàu [Yen Press]. Tổng: 76 ví dụ, 24 phân loại tâm trạng. Không nhiễm fan-TL.",
    "examples_by_mood": {}
}

for mood_name, mood_data in moods.items():
    mood_output = {
        "description": mood_desc_translations.get(mood_name, mood_data.get("description", "")),
        "instruction": "",
        "pattern": "",
        "vn_instruction": vn_instructions.get(mood_name, ""),
        "examples": []
    }

    for ex in mood_data.get("examples", []):
        ex_id = ex.get("id", "")
        ex_output = {
            "id": ex_id,
            "source": ex.get("source", ""),
            "text": ex.get("text", ""),
            "chapter": ex.get("chapter", ""),
            "why_premium": why_premium_translations.get(ex_id, ex.get("why_premium", ""))
        }
        if "context" in ex:
            ex_output["context"] = ex.get("context", "")
        if "word_count" in ex:
            ex_output["word_count"] = ex.get("word_count", 0)
        if "techniques" in ex:
            ex_output["techniques"] = ex.get("techniques", [])
        mood_output["examples"].append(ex_output)

    output_prose["examples_by_mood"][mood_name] = mood_output

output["real_world_jp_en_corpus"]["professional_prose_icl_examples"] = output_prose

# Print as JSON
print(json.dumps(output, ensure_ascii=False, indent=2))
