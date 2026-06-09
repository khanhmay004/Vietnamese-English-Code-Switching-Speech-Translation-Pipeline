import sys
import csv
import os
import yt_dlp

# Global list to store video data for the CSV
downloaded_videos_log = []

def progress_hook(d):
    """
    This function runs during the download process. 
    When a download finishes (before conversion), we capture the metadata.
    """
    if d['status'] == 'finished':
        # 'info_dict' contains the metadata of the video
        info = d.get('info_dict')
        
        # Safely extract relevant data
        video_data = {
            'channel_id': info.get('channel_id'),
            'video_id': info.get('id'),
            'upload_date': info.get('upload_date'),
            'title': info.get('title'),
            'url': info.get('webpage_url'),
            # Construct the final filename based on the requirement
            'final_filename': f"{info.get('channel_id')}_{info.get('id')}_{info.get('upload_date')}.mp3"
        }
        
        downloaded_videos_log.append(video_data)

def download_channels(url_list):
    ydl_opts = {
        # Format: Best Audio
        'format': 'bestaudio/best',
        
        # Convert to MP3
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        
        # Naming: ChannelID/ChannelID_VideoID_Date.ext
        'outtmpl': '%(channel_id)s/%(channel_id)s_%(id)s_%(upload_date)s.%(ext)s',
        
        # Add the hook to capture data
        'progress_hooks': [progress_hook],
        
        'ignoreerrors': True,
        'verbose': True
    }

    # Run the download
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download(url_list)

def save_csv():
    if not downloaded_videos_log:
        print("\nNo new videos were downloaded (or errors occurred), so no CSV was generated.")
        return

    csv_filename = 'download_report.csv'
    
    # Define the CSV headers
    headers = ['Channel ID', 'Video ID', 'Upload Date', 'Video Title', 'Original URL', 'Filename']

    print(f"\nGenerating {csv_filename}...")
    
    # Open file and write data
    try:
        with open(csv_filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            
            for video in downloaded_videos_log:
                writer.writerow({
                    'Channel ID': video['channel_id'],
                    'Video ID': video['video_id'],
                    'Upload Date': video['upload_date'],
                    'Video Title': video['title'],
                    'Original URL': video['url'],
                    'Filename': video['final_filename']
                })
        print(f"Successfully saved report to {os.path.abspath(csv_filename)}")
    except Exception as e:
        print(f"Failed to save CSV: {e}")

if __name__ == "__main__":
    # Capture all arguments after the script name
    input_urls = sys.argv[1:]

    if len(input_urls) < 1:
        print("Usage: python dl_channels_csv.py <url1> <url2> ...")
        sys.exit(1)

    print(f"Processing {len(input_urls)} channel(s)...")
    
    # 1. Download
    download_channels(input_urls)
    
    # 2. Generate CSV
    save_csv()