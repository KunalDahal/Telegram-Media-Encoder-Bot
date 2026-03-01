#!/usr/bin/env python3
import os
import re
import asyncio
from shlex import split as ssplit
from aiohttp import ClientSession
import aiofiles
from telegraph.aio import Telegraph
from telegraph.exceptions import RetryAfterError

class MediaInfoHelper:
    def __init__(self):
        self.telegraph = Telegraph(domain='graph.org')
        self.access_token = None
        self.author_name = "Encode Bot"
        self.author_url = "https://t.me/your_bot_username"
        
    async def create_account(self):
        """Create Telegraph account if not exists"""
        if not self.access_token:
            await self.telegraph.create_account(
                short_name='encodebot',
                author_name=self.author_name,
                author_url=self.author_url
            )
            self.access_token = self.telegraph.get_access_token()
            
    async def create_page(self, title, content):
        """Create a Telegraph page with retry on flood"""
        try:
            return await self.telegraph.create_page(
                title=title,
                author_name=self.author_name,
                author_url=self.author_url,
                html_content=content
            )
        except RetryAfterError as e:
            await asyncio.sleep(e.retry_after)
            return await self.create_page(title, content)
    
    async def download_file(self, url, save_path):
        """Download file from URL"""
        headers = {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                async with aiofiles.open(save_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(10 * 1024 * 1024):  # 10MB chunks
                        await f.write(chunk)
                        break  # Only download first 10MB for mediainfo
    
    async def download_media(self, client, message, media, save_path):
        """Download media from Telegram"""
        if media.file_size <= 50 * 1024 * 1024:  # 50MB
            await message.download(os.path.join(os.getcwd(), save_path))
        else:
            async for chunk in client.stream_media(media, limit=5):
                async with aiofiles.open(save_path, "ab") as f:
                    await f.write(chunk)
    
    async def run_mediainfo(self, file_path):
        """Run mediainfo command and return output"""
        process = await asyncio.create_subprocess_exec(
            'mediainfo', file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return stdout.decode('utf-8', errors='ignore')
    
    def parse_mediainfo(self, output, filename):
        """Parse mediainfo output to HTML for Telegraph"""
        section_dict = {
            'General': '📋', 
            'Video': '🎬', 
            'Audio': '🔊', 
            'Text': '📝', 
            'Menu': '📑'
        }
        
        html = f"<h3>📁 {filename}</h3><br>"
        trigger = False
        
        for line in output.split('\n'):
            for section, emoji in section_dict.items():
                if line.startswith(section):
                    trigger = True
                    if not line.startswith('General'):
                        html += '</pre><br>'
                    html += f"<h4>{emoji} {line.replace('Text', 'Subtitle')}</h4>"
                    break
            
            if trigger:
                html += '<br><pre>'
                trigger = False
            else:
                html += line + '\n'
        
        html += '</pre><br>'
        return html
    
    async def generate_mediainfo(self, client, message, file_path, filename):
        """Generate mediainfo and create Telegraph page"""
        try:
            # Run mediainfo
            output = await self.run_mediainfo(file_path)
            
            if not output:
                return None, "Failed to get media information"
            
            # Parse to HTML
            html_content = self.parse_mediainfo(output, filename)
            
            # Create Telegraph page
            await self.create_account()
            page = await self.create_page(
                title=f"MediaInfo - {filename[:50]}",
                content=html_content
            )
            
            return f"https://graph.org/{page['path']}", None
            
        except Exception as e:
            return None, str(e)
        finally:
            # Cleanup downloaded file
            if os.path.exists(file_path):
                os.remove(file_path)