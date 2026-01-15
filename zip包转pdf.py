import os
import zipfile
import tempfile
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
import io
import sys

def zip_to_pdf(zip_path, output_pdf=None, sort_by_name=True):
    """
    将ZIP文件中的图片按顺序转换为PDF
    
    Args:
        zip_path (str): ZIP文件路径
        output_pdf (str, optional): 输出PDF路径。如果为None，则使用ZIP文件名
        sort_by_name (bool): 是否按文件名排序。如果为False，则按ZIP中的顺序
    """
    
    # 检查文件是否存在
    if not os.path.exists(zip_path):
        print(f"错误: 文件 {zip_path} 不存在")
        return
    
    # 设置输出PDF文件名
    if output_pdf is None:
        base_name = os.path.splitext(zip_path)[0]
        output_pdf = base_name + '.pdf'
    
    # 支持的图片格式
    supported_formats = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp'}
    
    try:
        # 打开ZIP文件
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # 获取ZIP中的所有文件
            file_list = zip_ref.namelist()
            
            # 过滤出图片文件
            image_files = [f for f in file_list 
                          if os.path.splitext(f.lower())[1] in supported_formats]
            
            if not image_files:
                print("错误: ZIP文件中没有找到支持的图片文件")
                print(f"支持的格式: {', '.join(supported_formats)}")
                return
            
            print(f"找到 {len(image_files)} 张图片")
            
            # 按文件名排序（如果需要）
            if sort_by_name:
                image_files.sort()
                print("已按文件名排序")
            
            # 创建临时目录用于解压图片
            with tempfile.TemporaryDirectory() as temp_dir:
                # 创建PDF
                c = canvas.Canvas(output_pdf, pagesize=letter)
                
                for i, img_file in enumerate(image_files, 1):
                    try:
                        # 提取图片到临时目录
                        zip_ref.extract(img_file, temp_dir)
                        img_path = os.path.join(temp_dir, img_file)
                        
                        # 打开图片
                        img = Image.open(img_path)
                        
                        # 获取图片尺寸
                        img_width, img_height = img.size
                        
                        # 设置PDF页面大小（使用图片的尺寸或默认尺寸）
                        # 这里我们使用letter尺寸，但可以调整为图片尺寸
                        page_width, page_height = letter
                        
                        # 计算缩放比例，使图片适合页面
                        scale_width = page_width / img_width
                        scale_height = page_height / img_height
                        scale = min(scale_width, scale_height)
                        
                        # 计算图片在页面中的位置（居中）
                        new_width = img_width * scale
                        new_height = img_height * scale
                        x_offset = (page_width - new_width) / 2
                        y_offset = (page_height - new_height) / 2
                        
                        # 将图片添加到PDF
                        c.drawImage(img_path, x_offset, y_offset, 
                                   width=new_width, height=new_height)
                        
                        # 添加新页面（除非是最后一张图片）
                        if i < len(image_files):
                            c.showPage()
                        
                        print(f"已处理: {img_file} ({i}/{len(image_files)})")
                        
                    except Exception as e:
                        print(f"处理图片 {img_file} 时出错: {str(e)}")
                        continue
                
                # 保存PDF
                c.save()
                print(f"\nPDF已成功创建: {output_pdf}")
                print(f"共转换了 {i} 张图片")
                
    except zipfile.BadZipFile:
        print(f"错误: {zip_path} 不是有效的ZIP文件")
    except Exception as e:
        print(f"处理过程中出错: {str(e)}")

def batch_convert_zips_to_pdfs(folder_path, output_folder=None):
    """
    批量转换文件夹中的所有ZIP文件为PDF
    
    Args:
        folder_path (str): 包含ZIP文件的文件夹路径
        output_folder (str, optional): 输出PDF的文件夹路径
    """
    
    if not os.path.exists(folder_path):
        print(f"错误: 文件夹 {folder_path} 不存在")
        return
    
    # 获取所有ZIP文件
    zip_files = [f for f in os.listdir(folder_path) 
                if f.lower().endswith('.zip')]
    
    if not zip_files:
        print("错误: 文件夹中没有找到ZIP文件")
        return
    
    print(f"找到 {len(zip_files)} 个ZIP文件")
    
    # 设置输出文件夹
    if output_folder is None:
        output_folder = os.path.join(folder_path, 'pdf_output')
    
    # 创建输出文件夹
    os.makedirs(output_folder, exist_ok=True)
    
    # 批量转换
    for zip_file in zip_files:
        print(f"\n正在处理: {zip_file}")
        zip_path = os.path.join(folder_path, zip_file)
        output_pdf = os.path.join(output_folder, 
                                 os.path.splitext(zip_file)[0] + '.pdf')
        zip_to_pdf(zip_path, output_pdf)

def main():
    """主函数：提供命令行界面"""
    
    print("=" * 50)
    print("ZIP图片包转PDF工具")
    print("=" * 50)
    
    if len(sys.argv) > 1:
        # 命令行模式
        zip_path = sys.argv[1]
        output_pdf = sys.argv[2] if len(sys.argv) > 2 else None
        zip_to_pdf(zip_path, output_pdf)
    else:
        # 交互模式
        print("\n请选择操作:")
        print("1. 转换单个ZIP文件")
        print("2. 批量转换文件夹中的所有ZIP文件")
        
        choice = input("\n请输入选择 (1或2): ").strip()
        
        if choice == '1':
            zip_path = input("请输入ZIP文件路径: ").strip()
            output_pdf = input("请输入输出PDF路径（可选，直接回车使用默认名称）: ").strip()
            output_pdf = output_pdf if output_pdf else None
            
            sort_choice = input("是否按文件名排序图片？(y/n，默认y): ").strip().lower()
            sort_by_name = sort_choice != 'n'
            
            zip_to_pdf(zip_path, output_pdf, sort_by_name)
            
        elif choice == '2':
            folder_path = input("请输入包含ZIP文件的文件夹路径: ").strip()
            output_folder = input("请输入输出PDF的文件夹路径（可选）: ").strip()
            output_folder = output_folder if output_folder else None
            
            batch_convert_zips_to_pdfs(folder_path, output_folder)
        else:
            print("无效的选择")

if __name__ == "__main__":
    # 安装所需库的命令（如果需要）
    print("如果需要安装依赖库，请运行以下命令:")
    print("pip install Pillow reportlab")
    
    # 运行主程序
    main()
