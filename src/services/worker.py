import asyncio
import os
import shutil
from datetime import datetime
import concurrent.futures

class Worker:
    def __init__(self, task_queue, user_settings_getter, ffmpeg, client):
        self.task_queue = task_queue
        self.user_settings_getter = user_settings_getter
        self.ffmpeg = ffmpeg
        self.client = client
        self.temp_base = "./src/bin/tmp"
        self.thumbnails_dir = "./src/bin/thumbnails"
        self.running = False
        self.current_task = None
        self.current_task_id = None
        self.processing_task = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        os.makedirs(self.temp_base, exist_ok=True)
        os.makedirs(self.thumbnails_dir, exist_ok=True)

    async def start(self):
        self.running = True
        while self.running:
            try:
                if not self.current_task_id and not self.task_queue.is_processing():
                    next_task = self.task_queue.get_next_task()
                    if next_task:
                        self.current_task_id = next_task["task_id"]
                        self.current_task = next_task
                        self.task_queue.set_processing(True)
                        self.task_queue.update_status(self.current_task_id, "queued", 0)
                        
                        self.processing_task = asyncio.create_task(self.process_task(self.current_task))
                
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"Worker error: {e}")
                await asyncio.sleep(5)

    async def stop(self):
        self.running = False
        if self.processing_task:
            self.processing_task.cancel()
            try:
                await self.processing_task
            except:
                pass
        self.executor.shutdown(wait=False)

    async def cancel_task(self, task_id: str):
        try:
            if self.current_task_id == task_id and self.processing_task:
                self.processing_task.cancel()
                try:
                    await self.processing_task
                except asyncio.CancelledError:
                    print(f"Task {task_id} successfully cancelled")
                except Exception as e:
                    print(f"Error during task cancellation: {e}")
                
                self.current_task_id = None
                self.current_task = None
                self.task_queue.set_processing(False)
                self.task_queue.update_status(task_id, "cancelled", 0)
            
            if task_id in self.task_queue.queue:
                task = self.task_queue.get_task(task_id)
                if task:
                    try:
                        await self.client.send_message(
                            task["user_id"],
                            f"Task 🆔 {task_id[:8]} has been cancelled from queue."
                        )
                    except:
                        pass
                self.task_queue.queue.remove(task_id)
            
            if task_id in self.task_queue.tasks:
                del self.task_queue.tasks[task_id]
            
            task_folder = os.path.join(self.temp_base, task_id)
            if os.path.exists(task_folder):
                try:
                    shutil.rmtree(task_folder)
                except Exception as e:
                    print(f"Failed to clean up folder for task {task_id}: {e}")
                    
        except Exception as e:
            print(f"Error in cancel_task: {e}")

    async def process_task(self, task: dict):
        task_id = task["task_id"]
        task_folder = os.path.join(self.temp_base, task_id)
        
        downloaded_path = None
        encoded_path = None
        
        try:
            task["started_at"] = datetime.utcnow().isoformat()
            
            self.task_queue.update_status(task_id, "downloading", 10)
            
            from src.services.downloader import Downloader
            downloader = Downloader(self.temp_base, self.task_queue, task_id)
            downloaded_path = await downloader.download(
                client=self.client,
                task_data=task
            )
            
            if not downloaded_path or not os.path.exists(downloaded_path):
                raise Exception("Download failed: file not found")

            self.task_queue.update_status(task_id, "encoding", 40)
            
            user_settings = self.user_settings_getter(task["user_id"])
            settings = user_settings.get() if hasattr(user_settings, 'get') else user_settings
            
            from src.services.encoder import Encoder
            encoder = Encoder(self.ffmpeg)
            
            loop = asyncio.get_event_loop()
            encoded_path = await loop.run_in_executor(
                self.executor,
                self._run_encoding_sync,
                encoder, task, downloaded_path, settings
            )
            
            if not encoded_path or not os.path.exists(encoded_path):
                raise Exception("Encoding failed: output file not found")

            self.task_queue.update_status(task_id, "uploading", 80)

            from src.services.uploader import Uploader
            uploader = Uploader(self.client, task, self.task_queue)
            await uploader.upload()

            self.task_queue.remove_task(task_id)
            
            await self.notify_user(
                task["user_id"], 
                f"Task 🆔 {task_id[:8]} : {task['output_filename']} completed successfully!"
            )

        except asyncio.CancelledError:
            await self.notify_user(
                task["user_id"],
                f"Task Cancelled\n🆔 {task_id[:8]}"
            )
            self.task_queue.remove_task(task_id)
            
        except Exception as e:
            error_msg = str(e)
            print(f"Task {task_id} failed: {error_msg}")
            await self.notify_user(
                task["user_id"], 
                f"Task Failed\nError: {error_msg[:100]}\n🆔 {task_id[:8]}"
            )
            self.task_queue.remove_task(task_id)
        
        finally:
            for file_path in [downloaded_path, encoded_path]:
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except:
                        pass
            
            thumbnail_to_preserve = task.get("thumbnail_path", "")
            
            if thumbnail_to_preserve and os.path.exists(thumbnail_to_preserve) and thumbnail_to_preserve.startswith(task_folder):
                try:
                    import uuid
                    ext = os.path.splitext(thumbnail_to_preserve)[1]
                    new_thumb_path = os.path.join(self.thumbnails_dir, f"thumb_{task['user_id']}_{uuid.uuid4().hex[:8]}{ext}")
                    shutil.move(thumbnail_to_preserve, new_thumb_path)
                    
                    user_settings = self.user_settings_getter(task["user_id"])
                    if hasattr(user_settings, 'set_thumbnail'):
                        user_settings.set_thumbnail(new_thumb_path)
                except Exception as e:
                    print(f"Error preserving thumbnail: {e}")
            
            if os.path.exists(task_folder):
                try:
                    shutil.rmtree(task_folder)
                except Exception as e:
                    print(f"Error cleaning up task folder: {e}")
            
            self.current_task_id = None
            self.current_task = None
            self.task_queue.set_processing(False)

    def _run_encoding_sync(self, encoder, task, downloaded_path, settings):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                encoder.encode(
                    task_data=task,
                    input_path=downloaded_path,
                    settings=settings
                )
            )
        finally:
            loop.close()

    async def notify_user(self, user_id: int, message: str):
        try:
            await self.client.send_message(user_id, message)
        except Exception as e:
            print(f"Failed to notify user {user_id}: {e}")