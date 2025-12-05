import streamlit as st
import pandas as pd
import io
import json
import os
from google import genai
from google.genai.errors import APIError

# --- 1. THIẾT LẬP CẤU HÌNH VÀ KẾT NỐI GEMINI ---

st.set_page_config(
    page_title="Trích xuất Dữ liệu GCN QSDĐ bằng Gemini AI",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Kiểm tra và thiết lập Client
try:
    # Client tự động tìm khóa GEMINI_API_KEY từ biến môi trường
    client = genai.Client()
    MODEL_NAME = "gemini-2.5-flash"
except Exception:
    # Lỗi sẽ xuất hiện nếu khóa API chưa được đặt trong Secrets
    st.error("LỖI: Không tìm thấy GEMINI_API_KEY. Vui lòng thiết lập biến môi trường này trong mục Secrets của Streamlit Cloud.")
    st.stop()

# Định nghĩa cấu trúc JSON mong muốn
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "Chủ sử dụng": {"type": "string", "description": "Tên (và vợ/chồng) của người sử dụng đất."},
        "Thửa đất số": {"type": "string"},
        "Tờ bản đồ": {"type": "string"},
        "Diện tích tổng (m²)": {"type": "number"},
        "Đất ở (m²)": {"type": "number", "description": "Tổng diện tích Đất ở (nông thôn hoặc đô thị)."},
        "Đất trồng cây lâu năm (m²)": {"type": "number"},
        "Đất rừng SX / Lúa (m²)": {"type": "number", "description": "Nếu không có, hãy đặt là 0."},
        "Số vào sổ": {"type": "string"},
        "Số phát hành (Seri)": {"type": "string"},
        "Ngày kí": {"type": "string", "description": "Định dạng DD/MM/YYYY. Nếu thiếu ngày hoặc tháng, điền '..'."},
        "Xã/Thị trấn": {"type": "string", "description": "Chỉ lấy tên Xã hoặc Thị trấn, không bao gồm Thôn hoặc Huyện."}
    },
    "required": ["Chủ sử dụng", "Thửa đất số", "Diện tích tổng (m²)"]
}

# --- 2. HÀM TRÍCH XUẤT DỮ LIỆU SỬ DỤNG GEMINI API ---

def extract_data_via_gemini(uploaded_file):
    """
    Tải file lên Gemini API, yêu cầu trích xuất JSON có cấu trúc, sau đó xóa file.
    (Đã sửa lỗi mime_type và display_name bằng cách chỉ truyền file bytes.)
    """
    file = None
    try:
        file_bytes = uploaded_file.getvalue()
        
        st.caption(f"Đang tải **{uploaded_file.name}** lên Gemini...")
        
        # --- KHẮC PHỤC LỖI TẢI FILE ---
        # Chỉ truyền file bytes. SDK sẽ tự động xử lý loại file và đặt tên.
        file = client.files.upload(file=file_bytes)

        # Xây dựng Prompt
        prompt = (
            "Dựa trên nội dung của Giấy chứng nhận Quyền sử dụng đất (GCN) này, "
            "hãy trích xuất các trường thông tin sau. Trả lời CHỈ bằng định dạng JSON "
            "theo schema đã cung cấp. Đảm bảo tổng diện tích đất ở và đất trồng cây lâu năm bằng diện tích tổng."
        )

        # Gọi API với phản hồi có cấu trúc JSON
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[prompt, file],
            config={
                "response_mime_type": "application/json",
                "response_schema": JSON_SCHEMA,
            },
        )
        
        # Phân tích cú pháp JSON
        data = json.loads(response.text)
        data['Tên file nguồn'] = uploaded_file.name
        
        return data

    except APIError as e:
        st.error(f"Lỗi API khi xử lý {uploaded_file.name}: {e}")
        return None
    except json.JSONDecodeError:
        st.error(f"Lỗi phân tích JSON từ phản hồi của Gemini cho {uploaded_file.name}. Vui lòng kiểm tra lại chất lượng file PDF.")
        return None
    except Exception as e:
        st.error(f"Lỗi không xác định khi xử lý {uploaded_file.name}: {e}")
        return None
    finally:
        # Quan trọng: Xóa file khỏi dịch vụ Gemini sau khi xử lý xong
        if file:
            client.files.delete(name=file.name)
            st.caption(f"Đã xử lý và xóa file **{uploaded_file.name}** khỏi dịch vụ Gemini.")


# --- 3. GIAO DIỆN STREAMLIT CHÍNH ---

st.title("💡 Trích xuất GCN Đất đai (Sổ đỏ) bằng AI [Gemini]")

uploaded_files = st.file_uploader(
    "Tải lên các file GCN (Ưu tiên PDF)", 
    type=['pdf', 'txt'], 
    accept_multiple_files=True
)

if uploaded_files:
    results = []
    
    st.subheader(f"Đang xử lý {len(uploaded_files)} file bằng Gemini...")

    progress_bar = st.progress(0)
    
    for index, uploaded_file in enumerate(uploaded_files):
        data = extract_data_via_gemini(uploaded_file)
        if data:
            results.append(data)
        
        # Cập nhật thanh tiến trình
        progress_bar.progress((index + 1) / len(uploaded_files))
        
    # --- 4. TỔNG HỢP VÀ HIỂN THỊ KẾT QUẢ ---
    
    if results:
        df = pd.DataFrame(results)
        
        # Sắp xếp lại cột theo yêu cầu
        cols_order = [
            "Chủ sử dụng", "Thửa đất số", "Tờ bản đồ", "Diện tích tổng (m²)",
            "Đất ở (m²)", "Đất trồng cây lâu năm (m²)",
            "Đất rừng SX / Lúa (m²)", "Số vào sổ", "Số phát hành (Seri)", 
            "Ngày kí", "Xã/Thị trấn", "Tên file nguồn"
        ]
        df = df[cols_order]

        st.subheader("✅ Kết quả Trích xuất Hoàn chỉnh")
        st.dataframe(df, use_container_width=True)

        # TẠO NÚT TẢI XUỐNG FILE EXCEL
        excel_buffer = io.BytesIO()
        df.to_excel(excel_buffer, index=False, engine='xlsxwriter')
        excel_buffer.seek(0)
        
        st.download_button(
            label="Tải về file Excel (.xlsx)",
            data=excel_buffer,
            file_name="Ket_qua_trich_xuat_GCN_dat_dai_Gemini.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    st.success("Tất cả các file đã được xử lý xong!")
