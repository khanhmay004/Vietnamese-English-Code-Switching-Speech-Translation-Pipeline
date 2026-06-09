import csv
import os
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

CSV_FILE = 'download_report.csv'

def download_and_update_csv():
    # 1. Validation
    if not os.path.exists(CSV_FILE):
        print(f"Error: {CSV_FILE} not found. Please run the video downloader script first.")
        return

    print(f"Reading data from {CSV_FILE}...")

    # 2. Read the existing CSV into memory
    rows = []
    fieldnames = []
    
    with open(CSV_FILE, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        # Convert iterator to a list so we can modify it and write it back later
        rows = list(reader)

    # Ensure the new column header exists
    if 'Transcript Filename' not in fieldnames:
        fieldnames.append('Transcript Filename')

    # Initialize formatter
    formatter = TextFormatter()

    print(f"Processing {len(rows)} videos for transcripts...\n")

    # 3. Process each row
    for row in rows:
        channel_id = row.get('Channel ID')
        video_id = row.get('Video ID')
        upload_date = row.get('Upload Date')
        
        # Construct filenames and paths
        transcript_filename = f"{channel_id}_{video_id}_{upload_date}_transcript.txt"
        dir_path = os.path.join(channel_id) # Folder named after Channel ID
        file_path = os.path.join(dir_path, transcript_filename)

        # Create directory if it doesn't exist (safety check)
        os.makedirs(dir_path, exist_ok=True)

        # Check if we already downloaded this transcript to save time
        if os.path.exists(file_path):
            print(f"[EXISTS] Skipping download: {transcript_filename}")
            row['Transcript Filename'] = transcript_filename
            continue

        try:
            # Fetch Transcript (English or Auto-English)
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
            formatted_text = formatter.format_transcript(transcript_list)

            # Write to text file
            with open(file_path, 'w', encoding='utf-8') as text_file:
                text_file.write(formatted_text)

            print(f"[SUCCESS] Downloaded: {transcript_filename}")
            row['Transcript Filename'] = transcript_filename

        except (TranscriptsDisabled, NoTranscriptFound):
            print(f"[MISSING] No transcript found for: {video_id}")
            row['Transcript Filename'] = "Not Available"
        except Exception as e:
            print(f"[ERROR] {video_id}: {e}")
            row['Transcript Filename'] = "Error"

    # 4. Overwrite the original CSV file
    print(f"\nUpdating {CSV_FILE}...")
    
    try:
        with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print("CSV update complete.")
    except PermissionError:
        print(f"Error: Could not write to {CSV_FILE}. Is it open in Excel?")

if __name__ == "__main__":
    download_and_update_csv()