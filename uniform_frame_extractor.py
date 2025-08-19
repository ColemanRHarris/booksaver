"""
Uniform frame extraction for TikTok videos - 30 frames equally spread throughout video
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
        print(f"Warning: Could not set OpenCV thread count in uniform frame extractor: {cv2_thread_error}")
except Exception as e:
    print(f"Error: Failed to import OpenCV in uniform_frame_extractor: {e}")
    raise

import numpy as np
from typing import List
from pathlib import Path
import os


def extract_uniform_frames(video_path: str, num_frames: int = 30, debug_dir: str = None) -> List[np.ndarray]:
    """
    Extract frames uniformly distributed throughout the entire video
    
    Args:
        video_path: Path to the video file
        num_frames: Number of frames to extract (default: 30)
        debug_dir: Optional directory to save debug frames
        
    Returns:
        List of frames (numpy arrays) uniformly distributed across video
    """
    print(f"🎬 Extracting {num_frames} uniform frames from: {Path(video_path).name}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    
    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0
    
    print(f"📹 Video: {duration:.1f}s, {fps:.1f}fps, {total_frames} frames")
    
    if total_frames < num_frames:
        print(f"⚠️  Video has only {total_frames} frames, extracting all of them")
        num_frames = total_frames
    
    # Calculate frame indices uniformly distributed across the video
    if num_frames == 1:
        frame_indices = [total_frames // 2]  # Middle frame
    else:
        # Evenly distribute frames across the entire video length
        frame_indices = [int(i * (total_frames - 1) / (num_frames - 1)) for i in range(num_frames)]
    
    print(f"📋 Frame indices: {frame_indices[:5]}{'...' if len(frame_indices) > 5 else ''}")
    
    # Extract frames at calculated indices
    extracted_frames = []
    
    for i, frame_idx in enumerate(frame_indices):
        # Seek to specific frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        
        if ret and frame is not None:
            extracted_frames.append(frame.copy())
            timestamp = frame_idx / fps if fps > 0 else 0
            print(f"✅ Frame {i+1}/{num_frames}: index {frame_idx}, time {timestamp:.1f}s")
        else:
            print(f"❌ Failed to extract frame at index {frame_idx}")
    
    cap.release()
    
    print(f"🎯 Successfully extracted {len(extracted_frames)} frames")
    
    # Save debug frames if requested
    if debug_dir and extracted_frames:
        save_debug_frames(extracted_frames, debug_dir)
    
    return extracted_frames


def save_debug_frames(frames: List[np.ndarray], output_dir: str):
    """
    Save extracted frames for debugging purposes
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for i, frame in enumerate(frames):
        frame_path = output_path / f"uniform_frame_{i:02d}.jpg"
        cv2.imwrite(str(frame_path), frame)
    
    print(f"💾 Saved {len(frames)} debug frames to {output_dir}")


def extract_frames_with_skip(video_path: str, skip_start: float = 0.1, skip_end: float = 0.1, 
                           num_frames: int = 30, debug_dir: str = None) -> List[np.ndarray]:
    """
    Extract frames uniformly but skip beginning and end of video (for intro/outro)
    
    Args:
        video_path: Path to the video file
        skip_start: Fraction of video to skip at beginning (0.1 = 10%)
        skip_end: Fraction of video to skip at end (0.1 = 10%)
        num_frames: Number of frames to extract
        debug_dir: Optional directory to save debug frames
        
    Returns:
        List of frames uniformly distributed in middle portion of video
    """
    print(f"🎬 Extracting {num_frames} frames (skipping {skip_start*100}% start, {skip_end*100}% end)")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    
    # Get video properties
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / fps if fps > 0 else 0
    
    print(f"📹 Video: {duration:.1f}s, {fps:.1f}fps, {total_frames} frames")
    
    # Calculate start and end frames after skipping
    start_frame = int(total_frames * skip_start)
    end_frame = int(total_frames * (1 - skip_end))
    usable_frames = end_frame - start_frame
    
    if usable_frames < num_frames:
        print(f"⚠️  After skipping, only {usable_frames} frames available, extracting all of them")
        num_frames = usable_frames
    
    # Calculate frame indices uniformly distributed in the middle portion
    if num_frames == 1:
        frame_indices = [start_frame + usable_frames // 2]  # Middle frame
    else:
        frame_indices = [start_frame + int(i * usable_frames / (num_frames - 1)) for i in range(num_frames)]
    
    print(f"📋 Extracting from frames {start_frame} to {end_frame}")
    print(f"📋 Frame indices: {frame_indices[:5]}{'...' if len(frame_indices) > 5 else ''}")
    
    # Extract frames at calculated indices
    extracted_frames = []
    
    for i, frame_idx in enumerate(frame_indices):
        # Seek to specific frame
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        
        if ret and frame is not None:
            extracted_frames.append(frame.copy())
            timestamp = frame_idx / fps if fps > 0 else 0
            print(f"✅ Frame {i+1}/{num_frames}: index {frame_idx}, time {timestamp:.1f}s")
        else:
            print(f"❌ Failed to extract frame at index {frame_idx}")
    
    cap.release()
    
    print(f"🎯 Successfully extracted {len(extracted_frames)} frames")
    
    # Save debug frames if requested
    if debug_dir and extracted_frames:
        save_debug_frames(extracted_frames, debug_dir)
    
    return extracted_frames


# Main function for integration
def extract_30_uniform_frames(video_path: str, debug_dir: str = None) -> List[np.ndarray]:
    """
    Extract exactly 30 frames uniformly distributed across the entire video
    
    Args:
        video_path: Path to the video file
        debug_dir: Optional directory for debug output
        
    Returns:
        List of 30 frames (or fewer if video is very short)
    """
    return extract_uniform_frames(video_path, num_frames=30, debug_dir=debug_dir)