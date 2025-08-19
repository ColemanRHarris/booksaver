"""
Simple and reliable frame extraction for TikTok videos
Focuses on extracting frames with good book detection potential
"""

# Safe OpenCV import with threading fix
try:
    import cv2
    # Fix common OpenCV threading issues - safely check for setNumThreads
    try:
        if hasattr(cv2, 'setNumThreads'):
            cv2.setNumThreads(0)  # Prevent threading issues with multiprocessing
    except AttributeError:
        # setNumThreads not available in this OpenCV version, skip it
        pass
    except Exception as cv2_thread_error:
        print(f"Warning: Could not set OpenCV thread count in frame extractor: {cv2_thread_error}")
except Exception as e:
    print(f"Error: Failed to import OpenCV in simple_frame_extractor: {e}")
    raise

import numpy as np
from typing import List, Tuple
from pathlib import Path


class SimpleFrameExtractor:
    """Simple frame extractor optimized for book detection"""
    
    def __init__(self):
        # Simple parameters
        self.max_frames = 12  # Maximum frames to extract
        self.min_interval = 1.0  # Minimum seconds between frames
        self.quality_threshold = 0.1  # Lower threshold for more frames
        
    def extract_optimal_frames(self, video_path: str, output_dir: str = None) -> List[np.ndarray]:
        """
        Extract frames optimized for book detection
        
        Args:
            video_path: Path to the video file
            output_dir: Optional directory to save debug frames
            
        Returns:
            List of frames (numpy arrays) suitable for book detection
        """
        print(f"🎬 Starting simple frame extraction from: {Path(video_path).name}")
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
        
        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        
        print(f"📹 Video: {duration:.1f}s, {fps:.1f}fps, {frame_count} frames")
        
        # Extract candidate frames
        candidate_frames = self._extract_candidate_frames(cap, fps, duration)
        print(f"🔍 Found {len(candidate_frames)} candidate frames")
        
        # Score and select best frames
        scored_frames = self._score_and_select_frames(candidate_frames)
        print(f"✨ Selected {len(scored_frames)} final frames")
        
        # Save debug frames if requested
        if output_dir and scored_frames:
            self._save_debug_frames(scored_frames, output_dir)
        
        cap.release()
        return scored_frames
    
    def _extract_candidate_frames(self, cap: cv2.VideoCapture, fps: float, duration: float) -> List[Tuple[float, np.ndarray]]:
        """Extract candidate frames at regular intervals"""
        candidates = []
        
        # Calculate extraction interval
        # For short videos: extract more frequently
        # For long videos: extract less frequently
        if duration <= 15:
            interval = max(0.8, duration / 15)  # Every 0.8-1 seconds for short videos
        elif duration <= 30:
            interval = duration / 18  # 18 frames for medium videos
        else:
            interval = duration / 20  # 20 frames for long videos
        
        # Ensure minimum interval
        interval = max(interval, self.min_interval)
        
        current_time = 0.5  # Start after 0.5 seconds to avoid intro
        end_time = duration - 0.5  # Stop 0.5 seconds before end
        
        while current_time < end_time and len(candidates) < self.max_frames * 2:
            frame_idx = int(current_time * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            
            if ret:
                candidates.append((current_time, frame.copy()))
            
            current_time += interval
        
        return candidates
    
    def _score_and_select_frames(self, candidates: List[Tuple[float, np.ndarray]]) -> List[np.ndarray]:
        """Score frames and select the best ones"""
        scored_frames = []
        
        for timestamp, frame in candidates:
            score = self._score_frame_quality(frame)
            if score >= self.quality_threshold:
                scored_frames.append((score, timestamp, frame))
        
        # Sort by score (highest first)
        scored_frames.sort(key=lambda x: x[0], reverse=True)
        
        # Select top frames, ensuring time diversity
        selected_frames = []
        selected_times = []
        
        for score, timestamp, frame in scored_frames:
            # Check if this frame is too close to already selected frames
            too_close = any(abs(timestamp - t) < self.min_interval for t in selected_times)
            
            if not too_close and len(selected_frames) < self.max_frames:
                selected_frames.append(frame)
                selected_times.append(timestamp)
                print(f"  📍 Selected frame at {timestamp:.1f}s (score: {score:.3f})")
        
        return selected_frames
    
    def _score_frame_quality(self, frame: np.ndarray) -> float:
        """Score frame quality for book detection"""
        score = 0.0
        
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        
        # 1. Sharpness/Focus (books need to be in focus)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness_score = min(laplacian_var / 1000, 0.4)  # Cap at 0.4
        score += sharpness_score
        
        # 2. Brightness balance (avoid very dark or very bright frames)
        mean_brightness = np.mean(gray)
        brightness_score = 1.0 - abs(mean_brightness - 128) / 128
        score += brightness_score * 0.2
        
        # 3. Contrast (books with text should have good contrast)
        contrast = gray.std()
        contrast_score = min(contrast / 100, 0.3)  # Cap at 0.3
        score += contrast_score
        
        # 4. Edge density (books have text and edges)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / (h * w)
        edge_score = min(edge_density * 10, 0.3)  # Cap at 0.3
        score += edge_score
        
        # 5. Avoid motion blur (check for horizontal/vertical lines)
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        gradient_magnitude = np.sqrt(sobel_x**2 + sobel_y**2)
        gradient_score = min(np.mean(gradient_magnitude) / 100, 0.2)
        score += gradient_score
        
        # Bonus: Look for rectangular regions (potential books)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rect_bonus = 0
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > (h * w * 0.05):  # At least 5% of frame
                # Check if roughly rectangular
                epsilon = 0.02 * cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, epsilon, True)
                if len(approx) >= 4:  # Roughly rectangular
                    rect_bonus += 0.05
        
        score += min(rect_bonus, 0.2)  # Cap rectangle bonus
        
        return min(score, 1.0)  # Cap total score at 1.0
    
    def _save_debug_frames(self, frames: List[np.ndarray], output_dir: str):
        """Save debug frames for analysis"""
        try:
            debug_dir = Path(output_dir)
            debug_dir.mkdir(parents=True, exist_ok=True)
            
            for i, frame in enumerate(frames):
                filename = debug_dir / f"simple_frame_{i:02d}.jpg"
                cv2.imwrite(str(filename), frame)
            
            print(f"💾 Saved {len(frames)} debug frames to {debug_dir}")
        except Exception as e:
            print(f"⚠️ Could not save debug frames: {e}")