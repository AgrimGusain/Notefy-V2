import soundcard as sc
import soundfile as sf
import numpy as np
import threading
import queue
import os
from datetime import datetime

class SystemAudioRecorder:
    def __init__(self, output_dir=None):
        if output_dir is None:
            # Default to D:\Chrome-Summarizer\Audio-Notes\data\recordings reliably
            base_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.abspath(os.path.join(base_dir, "..", "data", "recordings"))

        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        self.audio_queue = queue.Queue()

        # Thread safety and state
        self._lock = threading.Lock()
        self.is_recording = False
        self.recording_thread = None

        self.session_id = None
        self.chunk_sequence = 0
        self.last_error = None

        # Configuration for audio chunking
        self.RATE = 16000

        self.BLOCK_SEC = 1.0  # read in 1-second increments
        self.BLOCK_FRAMES = int(self.RATE * self.BLOCK_SEC)

        self.CHUNK_DUR_SEC = 4.0  # transcription chunk duration
        self.CHUNK_FRAMES = int(self.RATE * self.CHUNK_DUR_SEC)

        self.OVERLAP_SEC = 0.5  # overlap to prevent word cutting
        self.STEP_SEC = self.CHUNK_DUR_SEC - self.OVERLAP_SEC # amount to advance (3.5s)
        self.STEP_FRAMES = int(self.RATE * self.STEP_SEC)

    def start_recording(self) -> dict:
        with self._lock:
            if self.is_recording:
                return {"session_id": self.session_id, "status": "already_recording"}

            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.chunk_sequence = 1
            self.is_recording = True
            self.last_error = None

            # Flush queue from previous session
            while not self.audio_queue.empty():
                try:
                    self.audio_queue.get_nowait()
                except queue.Empty:
                    break

            self.recording_thread = threading.Thread(target=self._record_loop, daemon=True)
            self.recording_thread.start()

            return {"session_id": self.session_id, "status": "started"}

    def _record_loop(self):
        try:
            # soundcard fetches the default speaker (loopback)
            default_speaker = sc.default_speaker()

            # We need the loopback "microphone" for this speaker
            mic = None
            for m in sc.all_microphones(include_loopback=True):
                if m.name == default_speaker.name:
                    mic = m
                    break

            # Fallback just in case
            if mic is None:
                mic = sc.get_microphone(default_speaker.id, include_loopback=True)

            # Accumulator for frames
            running_buffer = np.empty((0, 1), dtype=np.float32)
            total_processed_seconds = 0.0

            with mic.recorder(samplerate=self.RATE, channels=1) as recorder:
                while self.is_recording:
                    try:
                        # Record in small chunks of 1 second
                        data = recorder.record(numframes=self.BLOCK_FRAMES)
                        running_buffer = np.concatenate((running_buffer, data), axis=0)

                        # Once we have enough for a transcription window (e.g., 4 seconds)
                        while len(running_buffer) >= self.CHUNK_FRAMES:
                            chunk_data = running_buffer[:self.CHUNK_FRAMES]

                            start_secs = total_processed_seconds
                            end_secs = total_processed_seconds + self.CHUNK_DUR_SEC

                            self._write_chunk_and_queue(
                                audio_data=chunk_data,
                                start_seconds=start_secs,
                                end_seconds=end_secs,
                                is_final=False
                            )

                            # Advance buffer by step size (leaving overhang / overlap)
                            running_buffer = running_buffer[self.STEP_FRAMES:]
                            total_processed_seconds += self.STEP_SEC

                    except Exception as loop_e:
                        self.last_error = f"Error during record iteration: {loop_e}"
                        print(self.last_error)
                        break

            # Loop ended. Flush any remaining audio as final
            if len(running_buffer) > 0:
                duration_secs = len(running_buffer) / self.RATE
                self._write_chunk_and_queue(
                    audio_data=running_buffer,
                    start_seconds=total_processed_seconds,
                    end_seconds=total_processed_seconds + duration_secs,
                    is_final=True
                )
            else:
                # If there's no remaining audio, push a pure final sentinel item
                self.audio_queue.put({
                    "session_id": self.session_id,
                    "sequence": self.chunk_sequence,
                    "wav_path": None,
                    "start_seconds": total_processed_seconds,
                    "end_seconds": total_processed_seconds,
                    "is_final": True
                })

        except Exception as e:
            self.last_error = str(e)
            print(f"Error initializing WASAPI capture: {e}")
            self.is_recording = False

    def _write_chunk_and_queue(self, audio_data, start_seconds, end_seconds, is_final):
        # Determine output filename: e.g., session_20260911_153000_chunk_0001.wav
        filename = f"session_{self.session_id}_chunk_{self.chunk_sequence:04d}.wav"
        filepath = os.path.join(self.output_dir, filename)

        # Write to disk
        sf.write(filepath, audio_data, self.RATE)

        # Populate queue
        chunk_metadata = {
            "session_id": self.session_id,
            "sequence": self.chunk_sequence,
            "wav_path": filepath,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "is_final": is_final
        }

        self.audio_queue.put(chunk_metadata)
        self.chunk_sequence += 1

    def stop_recording(self) -> dict:
        with self._lock:
            if not self.is_recording:
                return {"session_id": self.session_id, "status": "already_stopped"}

            # Signal the thread to break out of the while loop
            self.is_recording = False
            thread_to_join = self.recording_thread

        if thread_to_join:
            thread_to_join.join()

        with self._lock:
            self.recording_thread = None
            return {"session_id": self.session_id, "status": "stopped"}

    def get_audio_chunk(self):
        """Returns the next parsed chunk dict or None if empty."""
        try:
            return self.audio_queue.get_nowait()
        except queue.Empty:
            return None
