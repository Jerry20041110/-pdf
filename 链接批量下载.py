import os
import re
import requests
import pyperclip
import threading
import queue
import time
from urllib.parse import urlparse, unquote
from datetime import datetime
from PIL import Image
from io import BytesIO
import hashlib
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import sys
import mimetypes

class ClipboardImageDownloader:
    def __init__(self):
        # 初始化默认配置
        self.config = {
            'save_dir': os.path.join(os.path.expanduser('~'), 'Downloads', 'ClipboardImages'),
            'max_workers': 5,
            'timeout': 30,
            'rename_pattern': '{index:03d}_{filename}',
            'auto_create_subdir': True,
            'subdir_pattern': '%Y-%m-%d',
            'deduplicate': True,
            'supported_extensions': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'],
            'min_file_size': 1024,  # 1KB
            'max_file_size': 50 * 1024 * 1024,  # 50MB
            'retry_attempts': 3,
            'retry_delay': 2,
        }
        
        # 加载用户配置
        self.load_config()
        
        # 创建保存目录
        self.ensure_save_dir()
        
        # 初始化下载队列和统计
        self.download_queue = queue.Queue()
        self.downloaded_files = []
        self.failed_urls = []
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'duplicate': 0
        }
        
        # 用于去重的集合
        self.url_hash_set = set()
        self.file_hash_set = set()
        
        # 线程控制
        self.threads = []
        self.running = False
        
    def load_config(self):
        """加载配置文件"""
        config_file = os.path.join(os.path.dirname(__file__), 'clipboard_downloader_config.json')
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                    self.config.update(user_config)
            except Exception as e:
                print(f"加载配置文件失败: {e}")
    
    def save_config(self):
        """保存配置文件"""
        config_file = os.path.join(os.path.dirname(__file__), 'clipboard_downloader_config.json')
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置文件失败: {e}")
    
    def ensure_save_dir(self):
        """确保保存目录存在"""
        if not os.path.exists(self.config['save_dir']):
            os.makedirs(self.config['save_dir'], exist_ok=True)
    
    def get_save_directory(self):
        """获取保存目录（考虑是否创建子目录）"""
        if self.config['auto_create_subdir']:
            subdir_name = datetime.now().strftime(self.config['subdir_pattern'])
            save_dir = os.path.join(self.config['save_dir'], subdir_name)
            os.makedirs(save_dir, exist_ok=True)
            return save_dir
        return self.config['save_dir']
    
    def extract_urls_from_clipboard(self):
        """从粘贴板提取URL"""
        try:
            clipboard_content = pyperclip.paste()
            
            # 如果没有内容，返回空列表
            if not clipboard_content:
                return []
            
            # 提取所有URL
            url_pattern = r'https?://[^\s<>"\']+'
            urls = re.findall(url_pattern, clipboard_content)
            
            # 清理URL（移除末尾的标点符号）
            cleaned_urls = []
            for url in urls:
                # 移除URL末尾的常见标点
                while url and url[-1] in '.,;:!?)}\'"':
                    url = url[:-1]
                cleaned_urls.append(url)
            
            return cleaned_urls
        
        except Exception as e:
            print(f"读取粘贴板失败: {e}")
            return []
    
    def is_image_url(self, url):
        """检查URL是否为图片链接"""
        try:
            # 检查文件扩展名
            parsed_url = urlparse(url)
            path = parsed_url.path.lower()
            
            # 检查是否有图片扩展名
            for ext in self.config['supported_extensions']:
                if path.endswith(ext):
                    return True
            
            # 如果没有扩展名，尝试通过HEAD请求检查Content-Type
            try:
                response = requests.head(url, timeout=10, allow_redirects=True)
                content_type = response.headers.get('Content-Type', '').lower()
                
                # 检查是否为图片类型
                image_types = ['image/jpeg', 'image/png', 'image/gif', 'image/bmp', 
                              'image/webp', 'image/tiff', 'image/svg+xml']
                for image_type in image_types:
                    if image_type in content_type:
                        return True
            except:
                pass
            
            return False
        
        except Exception:
            return False
    
    def get_filename_from_url(self, url, index=1):
        """从URL生成文件名"""
        try:
            parsed_url = urlparse(url)
            path = unquote(parsed_url.path)
            
            # 从路径提取文件名
            if path:
                filename = os.path.basename(path)
                if filename:
                    # 移除查询参数和片段
                    filename = filename.split('?')[0].split('#')[0]
                    
                    # 确保文件名有扩展名
                    name, ext = os.path.splitext(filename)
                    if not ext:
                        # 如果没有扩展名，尝试猜测
                        ext = mimetypes.guess_extension(parsed_url.path) or '.jpg'
                        filename = name + ext
                    
                    # 使用配置的命名模式
                    return self.config['rename_pattern'].format(
                        index=index,
                        filename=filename,
                        timestamp=int(time.time()),
                        date=datetime.now().strftime('%Y%m%d'),
                        time=datetime.now().strftime('%H%M%S')
                    )
            
            # 如果无法从URL提取文件名，使用默认名称
            return self.config['rename_pattern'].format(
                index=index,
                filename=f"image_{int(time.time())}.jpg",
                timestamp=int(time.time()),
                date=datetime.now().strftime('%Y%m%d'),
                time=datetime.now().strftime('%H%M%S')
            )
        
        except Exception:
            return f"image_{index:03d}_{int(time.time())}.jpg"
    
    def calculate_file_hash(self, filepath):
        """计算文件的MD5哈希值"""
        try:
            with open(filepath, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
            return file_hash
        except Exception:
            return None
    
    def download_image(self, url, save_path, retry_count=0):
        """下载单个图片"""
        try:
            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # 发送请求
            response = requests.get(url, headers=headers, timeout=self.config['timeout'], stream=True)
            response.raise_for_status()
            
            # 检查文件大小
            content_length = int(response.headers.get('Content-Length', 0))
            if content_length > self.config['max_file_size']:
                raise ValueError(f"文件太大 ({content_length} bytes)")
            
            if content_length > 0 and content_length < self.config['min_file_size']:
                raise ValueError(f"文件太小 ({content_length} bytes)")
            
            # 验证是否为图片
            content_type = response.headers.get('Content-Type', '').lower()
            if 'image/' not in content_type:
                # 如果不是图片类型，尝试读取前几个字节验证
                img_data = response.content[:100]  # 读取前100字节
                try:
                    Image.open(BytesIO(img_data))
                except:
                    raise ValueError("内容不是有效的图片")
            
            # 保存文件
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # 验证下载的文件
            if os.path.getsize(save_path) < self.config['min_file_size']:
                os.remove(save_path)
                raise ValueError("下载的文件太小")
            
            # 尝试打开图片验证
            try:
                with Image.open(save_path) as img:
                    img.verify()
            except:
                os.remove(save_path)
                raise ValueError("下载的文件不是有效的图片")
            
            return True
        
        except Exception as e:
            if retry_count < self.config['retry_attempts']:
                time.sleep(self.config['retry_delay'])
                return self.download_image(url, save_path, retry_count + 1)
            else:
                raise e
    
    def worker(self):
        """工作线程函数"""
        while self.running:
            try:
                # 从队列获取任务
                task = self.download_queue.get(timeout=1)
                if task is None:
                    break
                
                url, save_path, index = task
                
                try:
                    # 下载图片
                    success = self.download_image(url, save_path)
                    
                    if success:
                        # 计算文件哈希值（用于去重）
                        file_hash = self.calculate_file_hash(save_path)
                        
                        if self.config['deduplicate'] and file_hash:
                            if file_hash in self.file_hash_set:
                                # 重复文件，删除
                                os.remove(save_path)
                                self.stats['duplicate'] += 1
                                self.stats['skipped'] += 1
                                print(f"[跳过] {url} (重复文件)")
                            else:
                                self.file_hash_set.add(file_hash)
                                self.downloaded_files.append(save_path)
                                self.stats['success'] += 1
                                print(f"[成功] {url} -> {save_path}")
                        else:
                            self.downloaded_files.append(save_path)
                            self.stats['success'] += 1
                            print(f"[成功] {url} -> {save_path}")
                    
                except Exception as e:
                    self.failed_urls.append((url, str(e)))
                    self.stats['failed'] += 1
                    print(f"[失败] {url}: {e}")
                
                finally:
                    self.download_queue.task_done()
            
            except queue.Empty:
                continue
    
    def download_all(self, urls):
        """下载所有图片"""
        # 重置统计信息
        self.stats = {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0, 'duplicate': 0}
        self.downloaded_files = []
        self.failed_urls = []
        
        # 过滤出图片URL
        image_urls = []
        for url in urls:
            if self.is_image_url(url):
                # URL去重
                url_hash = hashlib.md5(url.encode()).hexdigest()
                if not self.config['deduplicate'] or url_hash not in self.url_hash_set:
                    self.url_hash_set.add(url_hash)
                    image_urls.append(url)
        
        if not image_urls:
            print("没有找到有效的图片链接")
            return False
        
        print(f"找到 {len(image_urls)} 个图片链接")
        
        # 准备保存目录
        save_dir = self.get_save_directory()
        
        # 将任务加入队列
        for i, url in enumerate(image_urls, 1):
            filename = self.get_filename_from_url(url, i)
            save_path = os.path.join(save_dir, filename)
            
            # 如果文件已存在，添加时间戳
            if os.path.exists(save_path):
                name, ext = os.path.splitext(filename)
                filename = f"{name}_{int(time.time())}{ext}"
                save_path = os.path.join(save_dir, filename)
            
            self.download_queue.put((url, save_path, i))
        
        self.stats['total'] = len(image_urls)
        
        # 启动工作线程
        self.running = True
        self.threads = []
        
        for i in range(min(self.config['max_workers'], len(image_urls))):
            thread = threading.Thread(target=self.worker)
            thread.daemon = True
            thread.start()
            self.threads.append(thread)
        
        # 等待所有任务完成
        self.download_queue.join()
        
        # 停止工作线程
        self.running = False
        for thread in self.threads:
            thread.join(timeout=1)
        
        return True
    
    def print_summary(self):
        """打印下载摘要"""
        print("\n" + "="*60)
        print("下载摘要")
        print("="*60)
        print(f"总计: {self.stats['total']}")
        print(f"成功: {self.stats['success']}")
        print(f"失败: {self.stats['failed']}")
        print(f"跳过: {self.stats['skipped']} (包含重复: {self.stats['duplicate']})")
        
        if self.downloaded_files:
            print(f"\n保存目录: {os.path.dirname(self.downloaded_files[0])}")
            print("\n下载的文件:")
            for file in self.downloaded_files[:10]:  # 最多显示10个文件
                print(f"  {os.path.basename(file)}")
            
            if len(self.downloaded_files) > 10:
                print(f"  ... 还有 {len(self.downloaded_files) - 10} 个文件")
        
        if self.failed_urls:
            print("\n失败的链接:")
            for url, error in self.failed_urls[:5]:  # 最多显示5个失败
                print(f"  {url}: {error}")
            
            if len(self.failed_urls) > 5:
                print(f"  ... 还有 {len(self.failed_urls) - 5} 个失败")


class ClipboardDownloaderGUI:
    """GUI界面"""
    def __init__(self, root):
        self.root = root
        self.root.title("智能粘贴板图片下载器")
        self.root.geometry("600x700")
        
        # 初始化下载器
        self.downloader = ClipboardImageDownloader()
        
        # 创建UI元素
        self.setup_ui()
        
    def setup_ui(self):
        """设置UI界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # 标题
        title_label = ttk.Label(main_frame, text="智能粘贴板图片下载器", 
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # 当前粘贴板内容
        ttk.Label(main_frame, text="当前粘贴板内容:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.clipboard_text = tk.Text(main_frame, height=6, width=60)
        self.clipboard_text.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 提取的链接
        ttk.Label(main_frame, text="提取的图片链接:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.urls_text = tk.Text(main_frame, height=8, width=60)
        self.urls_text.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=3, pady=10)
        
        # 按钮
        self.refresh_btn = ttk.Button(button_frame, text="刷新粘贴板", command=self.refresh_clipboard)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)
        
        self.download_btn = ttk.Button(button_frame, text="开始下载", command=self.start_download)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        
        self.settings_btn = ttk.Button(button_frame, text="设置", command=self.open_settings)
        self.settings_btn.pack(side=tk.LEFT, padx=5)
        
        # 进度条
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=6, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        
        # 状态标签
        self.status_label = ttk.Label(main_frame, text="就绪")
        self.status_label.grid(row=7, column=0, columnspan=3, pady=5)
        
        # 日志文本框
        ttk.Label(main_frame, text="日志:").grid(row=8, column=0, sticky=tk.W, pady=5)
        self.log_text = tk.Text(main_frame, height=10, width=60)
        self.log_text.grid(row=9, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 滚动条
        scrollbar = ttk.Scrollbar(main_frame, command=self.log_text.yview)
        scrollbar.grid(row=9, column=3, sticky=(tk.N, tk.S))
        self.log_text['yscrollcommand'] = scrollbar.set
        
        # 配置网格权重
        main_frame.rowconfigure(9, weight=1)
        
        # 初始刷新
        self.refresh_clipboard()
        
    def log(self, message):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def refresh_clipboard(self):
        """刷新粘贴板内容"""
        try:
            # 清空文本框
            self.clipboard_text.delete(1.0, tk.END)
            self.urls_text.delete(1.0, tk.END)
            
            # 获取粘贴板内容
            content = pyperclip.paste()
            self.clipboard_text.insert(1.0, content)
            
            # 提取URL
            urls = self.downloader.extract_urls_from_clipboard()
            image_urls = [url for url in urls if self.downloader.is_image_url(url)]
            
            # 显示URL
            for url in image_urls:
                self.urls_text.insert(tk.END, f"{url}\n")
            
            self.log(f"找到 {len(image_urls)} 个图片链接")
            self.status_label.config(text=f"找到 {len(image_urls)} 个图片链接")
            
        except Exception as e:
            self.log(f"刷新失败: {e}")
    
    def start_download(self):
        """开始下载"""
        # 获取URL
        urls_text = self.urls_text.get(1.0, tk.END).strip().split('\n')
        urls = [url.strip() for url in urls_text if url.strip()]
        
        if not urls:
            messagebox.showwarning("警告", "没有找到图片链接")
            return
        
        # 禁用按钮
        self.refresh_btn.config(state=tk.DISABLED)
        self.download_btn.config(state=tk.DISABLED)
        self.settings_btn.config(state=tk.DISABLED)
        
        # 启动进度条
        self.progress.start()
        self.status_label.config(text="下载中...")
        
        # 在单独的线程中下载
        def download_thread():
            try:
                success = self.downloader.download_all(urls)
                
                # 在主线程中更新UI
                self.root.after(0, self.on_download_complete, success)
                
            except Exception as e:
                self.root.after(0, self.on_download_error, str(e))
        
        # 启动下载线程
        threading.Thread(target=download_thread, daemon=True).start()
    
    def on_download_complete(self, success):
        """下载完成回调"""
        # 停止进度条
        self.progress.stop()
        
        # 启用按钮
        self.refresh_btn.config(state=tk.NORMAL)
        self.download_btn.config(state=tk.NORMAL)
        self.settings_btn.config(state=tk.NORMAL)
        
        # 显示结果
        self.downloader.print_summary()
        
        # 更新日志
        self.log("下载完成!")
        self.log(f"成功: {self.downloader.stats['success']}, 失败: {self.downloader.stats['failed']}")
        
        # 更新状态
        self.status_label.config(text=f"下载完成: {self.downloader.stats['success']} 成功, {self.downloader.stats['failed']} 失败")
        
        # 显示摘要
        message = f"下载完成!\n\n"
        message += f"总计: {self.downloader.stats['total']}\n"
        message += f"成功: {self.downloader.stats['success']}\n"
        message += f"失败: {self.downloader.stats['failed']}\n"
        message += f"保存目录: {self.downloader.get_save_directory()}"
        
        messagebox.showinfo("完成", message)
    
    def on_download_error(self, error):
        """下载错误回调"""
        # 停止进度条
        self.progress.stop()
        
        # 启用按钮
        self.refresh_btn.config(state=tk.NORMAL)
        self.download_btn.config(state=tk.NORMAL)
        self.settings_btn.config(state=tk.NORMAL)
        
        # 显示错误
        self.log(f"下载出错: {error}")
        self.status_label.config(text="下载出错")
        messagebox.showerror("错误", f"下载过程中出错:\n{error}")
    
    def open_settings(self):
        """打开设置窗口"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("500x500")
        
        # 创建设置UI
        self.create_settings_ui(settings_window)
    
    def create_settings_ui(self, window):
        """创建设置UI"""
        # 主框架
        main_frame = ttk.Frame(window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 保存目录
        ttk.Label(main_frame, text="保存目录:").grid(row=0, column=0, sticky=tk.W, pady=5)
        
        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.dir_var = tk.StringVar(value=self.downloader.config['save_dir'])
        dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var, width=40)
        dir_entry.pack(side=tk.LEFT, padx=(0, 5))
        
        def browse_dir():
            directory = filedialog.askdirectory(initialdir=self.downloader.config['save_dir'])
            if directory:
                self.dir_var.set(directory)
        
        ttk.Button(dir_frame, text="浏览...", command=browse_dir).pack(side=tk.LEFT)
        
        # 线程数
        ttk.Label(main_frame, text="最大线程数:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.threads_var = tk.IntVar(value=self.downloader.config['max_workers'])
        ttk.Spinbox(main_frame, from_=1, to=20, textvariable=self.threads_var, width=10).grid(row=2, column=1, sticky=tk.W, pady=5)
        
        # 自动创建子目录
        self.subdir_var = tk.BooleanVar(value=self.downloader.config['auto_create_subdir'])
        ttk.Checkbutton(main_frame, text="自动创建按日期命名的子目录", variable=self.subdir_var).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 去重
        self.dedup_var = tk.BooleanVar(value=self.downloader.config['deduplicate'])
        ttk.Checkbutton(main_frame, text="下载时去重", variable=self.dedup_var).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        # 命名模式
        ttk.Label(main_frame, text="文件名模式:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.pattern_var = tk.StringVar(value=self.downloader.config['rename_pattern'])
        ttk.Entry(main_frame, textvariable=self.pattern_var, width=40).grid(row=5, column=1, sticky=tk.W, pady=5)
        ttk.Label(main_frame, text="可用变量: {index}, {filename}, {timestamp}, {date}, {time}", 
                 font=("Arial", 8)).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        # 按钮框架
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=7, column=0, columnspan=2, pady=20)
        
        def save_settings():
            # 保存设置
            self.downloader.config['save_dir'] = self.dir_var.get()
            self.downloader.config['max_workers'] = self.threads_var.get()
            self.downloader.config['auto_create_subdir'] = self.subdir_var.get()
            self.downloader.config['rename_pattern'] = self.pattern_var.get()
            self.downloader.config['deduplicate'] = self.dedup_var.get()
            
            # 保存到文件
            self.downloader.save_config()
            
            # 重新创建保存目录
            self.downloader.ensure_save_dir()
            
            messagebox.showinfo("成功", "设置已保存")
            window.destroy()
        
        def cancel_settings():
            window.destroy()
        
        ttk.Button(button_frame, text="保存", command=save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=cancel_settings).pack(side=tk.LEFT, padx=5)


def main():
    """主函数"""
    # 检查依赖
    try:
        import pyperclip
        import requests
        from PIL import Image
    except ImportError as e:
        print("缺少依赖库，请安装:")
        print("pip install pyperclip requests Pillow")
        print(f"错误详情: {e}")
        return
    
    # 检查是否以GUI模式运行
    if len(sys.argv) > 1 and sys.argv[1] == '--cli':
        # 命令行模式
        run_cli_mode()
    else:
        # GUI模式
        try:
            root = tk.Tk()
            app = ClipboardDownloaderGUI(root)
            root.mainloop()
        except Exception as e:
            print(f"GUI模式启动失败: {e}")
            print("尝试使用命令行模式: python script.py --cli")


def run_cli_mode():
    """运行命令行模式"""
    print("="*60)
    print("粘贴板图片下载器 - 命令行模式")
    print("="*60)
    
    downloader = ClipboardImageDownloader()
    
    while True:
        print("\n选项:")
        print("1. 从粘贴板提取并下载图片")
        print("2. 输入URL列表下载")
        print("3. 查看当前粘贴板内容")
        print("4. 设置")
        print("5. 退出")
        
        choice = input("\n请选择 (1-5): ").strip()
        
        if choice == '1':
            # 从粘贴板提取并下载
            urls = downloader.extract_urls_from_clipboard()
            if urls:
                print(f"找到 {len(urls)} 个链接")
                downloader.download_all(urls)
                downloader.print_summary()
            else:
                print("粘贴板中没有找到链接")
        
        elif choice == '2':
            # 手动输入URL
            print("请输入图片URL（每行一个，输入空行结束）:")
            urls = []
            while True:
                url = input().strip()
                if not url:
                    break
                urls.append(url)
            
            if urls:
                downloader.download_all(urls)
                downloader.print_summary()
        
        elif choice == '3':
            # 查看粘贴板内容
            try:
                content = pyperclip.paste()
                print("\n当前粘贴板内容:")
                print("-"*40)
                print(content[:500] + ("..." if len(content) > 500 else ""))
                print("-"*40)
                
                urls = downloader.extract_urls_from_clipboard()
                image_urls = [url for url in urls if downloader.is_image_url(url)]
                print(f"\n提取到 {len(image_urls)} 个图片链接")
                
                if image_urls:
                    print("图片链接:")
                    for i, url in enumerate(image_urls[:10], 1):
                        print(f"{i}. {url}")
                    if len(image_urls) > 10:
                        print(f"... 还有 {len(image_urls) - 10} 个链接")
            
            except Exception as e:
                print(f"读取粘贴板失败: {e}")
        
        elif choice == '4':
            # 设置
            print("\n当前设置:")
            for key, value in downloader.config.items():
                print(f"  {key}: {value}")
            
            change = input("\n是否修改设置？(y/n): ").lower()
            if change == 'y':
                # 这里可以添加更详细的设置修改逻辑
                new_dir = input(f"保存目录 [{downloader.config['save_dir']}]: ").strip()
                if new_dir:
                    downloader.config['save_dir'] = new_dir
                    downloader.ensure_save_dir()
                    downloader.save_config()
                    print("设置已保存")
        
        elif choice == '5':
            print("再见！")
            break
        
        else:
            print("无效选择，请重试")


if __name__ == "__main__":
    main()
