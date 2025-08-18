"""
Smart frame extraction for TikTok videos to capture each unique book once
"""

import cv2
import numpy as np
from typing import List, Dict, Tuple, Optional
from pathlib import Path
import time
from collections import defaultdict
import hashlib


class SmartFrameExtractor:
    """Intelligently extract frames from TikTok videos to capture unique books"""
    
    def __init__(self):
        # Parameters for scene change detection
        self.scene_change_threshold = 0.2  # Minimum difference to consider scene change (more sensitive)
        self.min_scene_duration = 0.8  # Minimum seconds between captures (reduced)
        self.max_frames_per_video = 10  # Maximum frames to extract (increased)
        
        # Parameters for book detection optimization
        self.book_area_threshold = 0.05  # Minimum area for book detection
        self.stability_frames = 5  # Frames to check for stability
        self.similarity_threshold = 0.90  # Similarity threshold for duplicate detection (increased to keep more frames)
        
    def extract_optimal_frames(self, video_path: str, output_dir: str = None) -> List[np.ndarray]:
        """
        Extract optimal frames from video to capture each unique book
        
        Args:
            video_path: Path to the video file
            output_dir: Optional directory to save debug frames
            
        Returns:
            List of frames (numpy arrays) containing unique books
        """
        print(f"🎬 Starting smart frame extraction from: {Path(video_path).name}")
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")
        
        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        
        print(f"📹 Video: {duration:.1f}s, {fps:.1f}fps, {frame_count} frames")
        
        # Step 1: Quick pass to identify scene changes and potential book moments
        scene_changes = self._detect_scene_changes(cap, fps)
        print(f"🎭 Detected {len(scene_changes)} scene changes")
        
        # Step 2: Analyze each scene for book presence and stability
        optimal_moments = self._find_optimal_book_moments(cap, scene_changes, fps)
        print(f"📚 Found {len(optimal_moments)} optimal book moments")
        
        # Step 3: Extract frames at optimal moments
        extracted_frames = self._extract_frames_at_moments(cap, optimal_moments)
        
        # Step 4: Remove duplicate/similar frames
        unique_frames = self._remove_duplicate_frames(extracted_frames)
        print(f"✨ Final unique frames: {len(unique_frames)}")
        
        # Step 5: Save debug frames if requested
        if output_dir:
            self._save_debug_frames(unique_frames, output_dir)
        
        cap.release()
        return unique_frames
    
    def _detect_scene_changes(self, cap: cv2.VideoCapture, fps: float) -> List[float]:
        """
        Detect scene changes using histogram comparison
        Returns list of timestamps where scenes change
        """
        scene_changes = [0.0]  # Always include start
        prev_hist = None
        frame_idx = 0
        
        # Sample every 0.5 seconds for quick analysis
        sample_interval = max(1, int(fps * 0.5))
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_idx % sample_interval == 0:
                # Calculate histogram for scene change detection
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
                hist = cv2.normalize(hist, hist).flatten()
                
                if prev_hist is not None:
                    # Compare with previous histogram
                    correlation = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    
                    # If correlation is low, we have a scene change
                    if correlation < (1.0 - self.scene_change_threshold):
                        timestamp = frame_idx / fps
                        # Ensure minimum distance between scene changes
                        if not scene_changes or timestamp - scene_changes[-1] >= self.min_scene_duration:
                            scene_changes.append(timestamp)
                
                prev_hist = hist
            
            frame_idx += 1
        
        # Reset video capture to beginning
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        return scene_changes
    
    def _find_optimal_book_moments(self, cap: cv2.VideoCapture, 
                                 scene_changes: List[float], fps: float) -> List[float]:
        """
        Analyze each scene to find the best moment to capture books
        """
        optimal_moments = []
        
        for i, scene_start in enumerate(scene_changes):
            scene_end = scene_changes[i + 1] if i + 1 < len(scene_changes) else None
            
            # Analyze this scene for the best book capture moment
            best_moment = self._analyze_scene_for_books(cap, scene_start, scene_end, fps)
            
            if best_moment is not None:
                optimal_moments.append(best_moment)
        
        # Limit total frames extracted
        if len(optimal_moments) > self.max_frames_per_video:
            # Keep frames evenly distributed across video
            indices = np.linspace(0, len(optimal_moments) - 1, self.max_frames_per_video, dtype=int)
            optimal_moments = [optimal_moments[i] for i in indices]
        
        return optimal_moments
    
    def _analyze_scene_for_books(self, cap: cv2.VideoCapture, 
                               scene_start: float, scene_end: Optional[float], fps: float) -> Optional[float]:
        """
        Analyze a scene to find the optimal moment for book capture
        """
        start_frame = int(scene_start * fps)
        end_frame = int(scene_end * fps) if scene_end else int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Limit scene analysis to avoid processing too many frames
        max_frames_to_check = min(int(fps * 3), end_frame - start_frame)  # Max 3 seconds per scene
        
        if max_frames_to_check < fps * 0.5:  # Skip very short scenes
            return None
        
        # Sample frames throughout the scene
        frame_indices = np.linspace(start_frame, min(start_frame + max_frames_to_check, end_frame - 1), 
                                  min(15, max_frames_to_check), dtype=int)
        
        best_score = 0
        best_timestamp = None
        
        for frame_idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue
            
            # Score this frame for book detection quality
            score = self._score_frame_for_books(frame)
            
            if score > best_score:
                best_score = score
                best_timestamp = frame_idx / fps
        
        # Only return if we found a reasonable score (lowered threshold)
        return best_timestamp if best_score > 0.15 else None
    
    def _score_frame_for_books(self, frame: np.ndarray) -> float:
        """
        Score a frame based on its likelihood of containing good book captures
        """
        score = 0.0
        
        # Convert to different color spaces for analysis
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # 1. Edge density (books have lots of text/edges)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        score += min(edge_density * 2, 0.3)  # Cap at 0.3
        
        # 2. Rectangular shapes (book detection)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rectangular_score = 0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > frame.shape[0] * frame.shape[1] * self.book_area_threshold:
                # Check if contour is roughly rectangular
                epsilon = 0.02 * cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, epsilon, True)
                if len(approx) == 4:  # Rectangular
                    rectangular_score += 0.1
        
        score += min(rectangular_score, 0.3)  # Cap at 0.3
        
        # 3. Color variety (colorful book covers)
        color_std = np.std(hsv[:, :, 1])  # Saturation standard deviation
        score += min(color_std / 255 * 0.2, 0.2)  # Cap at 0.2
        
        # 4. Brightness balance (not too dark/bright)
        brightness = np.mean(gray)
        brightness_score = 1 - abs(brightness - 128) / 128  # Best at mid-brightness
        score += brightness_score * 0.2
        
        return score
    
    def _extract_frames_at_moments(self, cap: cv2.VideoCapture, moments: List[float]) -> List[Tuple[float, np.ndarray]]:
        """
        Extract frames at specified timestamps
        """
        frames = []
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        for timestamp in moments:
            frame_idx = int(timestamp * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            
            if ret:
                frames.append((timestamp, frame.copy()))
        
        return frames
    
    def _remove_duplicate_frames(self, frames: List[Tuple[float, np.ndarray]]) -> List[np.ndarray]:
        """
        Remove duplicate or very similar frames to ensure unique book captures
        """
        if not frames:
            return []
        
        unique_frames = []
        frame_hashes = []
        
        for timestamp, frame in frames:
            # Create perceptual hash of the frame for similarity comparison
            frame_hash = self._perceptual_hash(frame)
            
            # Check similarity with existing frames
            is_similar = False
            for existing_hash in frame_hashes:
                similarity = self._hash_similarity(frame_hash, existing_hash)
                if similarity > self.similarity_threshold:
                    is_similar = True
                    break
            
            if not is_similar:
                unique_frames.append(frame)
                frame_hashes.append(frame_hash)
        
        return unique_frames
    
    def _perceptual_hash(self, frame: np.ndarray, hash_size: int = 16) -> str:
        """
        Create perceptual hash for image similarity comparison
        """
        # Resize to small size
        resized = cv2.resize(frame, (hash_size, hash_size))
        
        # Convert to grayscale
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        
        # Calculate mean
        mean = np.mean(gray)
        
        # Create binary hash
        binary_str = ''.join(['1' if pixel > mean else '0' for pixel in gray.flatten()])
        
        # Convert to hex string for compact representation
        return hex(int(binary_str, 2))
    
    def _hash_similarity(self, hash1: str, hash2: str) -> float:
        """
        Calculate similarity between two perceptual hashes
        """
        try:
            # Convert hex hashes to binary
            bin1 = bin(int(hash1, 16))[2:].zfill(256)
            bin2 = bin(int(hash2, 16))[2:].zfill(256)
            
            # Calculate Hamming distance
            hamming_distance = sum(c1 != c2 for c1, c2 in zip(bin1, bin2))
            
            # Convert to similarity (1.0 = identical, 0.0 = completely different)
            similarity = 1.0 - (hamming_distance / len(bin1))
            return similarity
        except (ValueError, TypeError):
            return 0.0
    
    def _save_debug_frames(self, frames: List[np.ndarray], output_dir: str):
        """
        Save extracted frames for debugging purposes
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for i, frame in enumerate(frames):
            frame_path = output_path / f"smart_frame_{i:02d}.jpg"
            cv2.imwrite(str(frame_path), frame)
        
        print(f"💾 Saved {len(frames)} debug frames to {output_dir}")


def create_smart_frame_extractor() -> SmartFrameExtractor:
    """Create a smart frame extractor instance"""
    return SmartFrameExtractor()


# Integration function for existing pipeline
def extract_smart_frames_from_video(video_path: str, debug_dir: str = None) -> List[np.ndarray]:
    """
    Extract frames intelligently from TikTok video to capture unique books
    
    Args:
        video_path: Path to the video file
        debug_dir: Optional directory for debug output
        
    Returns:
        List of frames optimized for book detection
    """
    extractor = create_smart_frame_extractor()
    return extractor.extract_optimal_frames(video_path, debug_dir)