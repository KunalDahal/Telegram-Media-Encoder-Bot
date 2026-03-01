import os
import asyncio
import logging

class FFmpeg:
    def __init__(self):
        self.encode_progress = 0
        self.current_stage = ""
        self.current_process = None
        
    def _get_resolution_dimensions(self, resolution_str):
        resolution_map = {
            '1080p': '1920x1080',
            '720p': '1280x720',
            '480p': '854x480',
            '360p': '640x360'
        }
        
        clean_res = resolution_str.lower().strip()
        if not clean_res.endswith('p'):
            clean_res = clean_res + 'p'
        
        if clean_res in resolution_map:
            return resolution_map[clean_res]
        
        return '1920x1080'
    
    def build_command(self, input_path, output_path, settings):
        input_path = os.path.abspath(input_path)
        output_path = os.path.abspath(output_path)
        
        if input_path == output_path:
            raise ValueError("Input and output paths cannot be the same")
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        resolution_str = settings.get('resolution', '1080p')
        dimensions = self._get_resolution_dimensions(resolution_str)
        width, height = dimensions.split('x')
        
        codec = settings.get('codec', 'libx264')
        if codec not in ['libx264', 'libx265', 'h264', 'h265']:
            codec = 'libx264'
        
        cmd = [
            'ffmpeg',
            '-i', input_path,
            '-c:v', codec,
            '-preset', settings.get('preset', 'medium'),
            '-crf', str(settings.get('crf', 23)),
            '-vf', f'scale={dimensions}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            '-b:a', settings.get('audio_bitrate', '128k'),
            '-movflags', '+faststart',
        ]
        
        metadata = settings.get('metadata', {})
        
        if metadata.get('title') and metadata['title'].strip():
            title = metadata['title'].strip().replace('"', '\\"').replace("'", "\\'")
            cmd.extend(['-metadata', f'title={title}'])
        
        if metadata.get('author') and metadata['author'].strip():
            author = metadata['author'].strip().replace('"', '\\"').replace("'", "\\'")
            cmd.extend(['-metadata', f'artist={author}'])
        
        if metadata.get('encoder') and metadata['encoder'].strip():
            encoder = metadata['encoder'].strip().replace('"', '\\"').replace("'", "\\'")
            cmd.extend(['-metadata', f'encoder={encoder}'])
        
        cmd.extend(['-y', output_path])
        
        return cmd
    
    async def execute(self, cmd):
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.current_process = process
            
            try:
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    error_msg = stderr.decode('utf-8', errors='ignore')[:500]
                    return False, f"FFmpeg error (code {process.returncode}): {error_msg}"
                
                output_file = cmd[-1]
                if not os.path.exists(output_file):
                    return False, f"Output file not created: {output_file}"
                
                if os.path.getsize(output_file) == 0:
                    return False, f"Output file is empty: {output_file}"
                
                return True, None
                
            except asyncio.CancelledError:
                if self.current_process and self.current_process.returncode is None:
                    try:
                        self.current_process.terminate()
                        await asyncio.sleep(0.5)
                        if self.current_process.returncode is None:
                            self.current_process.kill()
                        await self.current_process.wait()
                    except:
                        pass
                raise
                
        except FileNotFoundError:
            return False, "FFmpeg not found in system PATH"
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
        finally:
            self.current_process = None