import psutil
import time
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import threading
import os

@dataclass
class ResourceSnapshot:
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_usage_percent: float
    process_count: int

class SystemMonitor:
    def __init__(self, history_minutes: int = 60):
        self.history_minutes = history_minutes
        self.snapshots: List[ResourceSnapshot] = []
        self.monitoring = False
        self.monitor_thread = None
        self._lock = threading.Lock()
    
    def start_monitoring(self, interval_seconds: int = 30):
        """Start continuous monitoring in background thread"""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, args=(interval_seconds,))
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        print(f"🔍 System monitoring started (interval: {interval_seconds}s)")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
    
    def _monitor_loop(self, interval_seconds: int):
        """Background monitoring loop"""
        while self.monitoring:
            try:
                self._take_snapshot()
                time.sleep(interval_seconds)
            except Exception as e:
                print(f"⚠️ Monitoring error: {e}")
                time.sleep(interval_seconds)
    
    def _take_snapshot(self):
        """Take a system resource snapshot"""
        try:
            # Get current stats
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            process_count = len(psutil.pids())
            
            snapshot = ResourceSnapshot(
                timestamp=datetime.utcnow(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / (1024 * 1024),
                memory_available_mb=memory.available / (1024 * 1024),
                disk_usage_percent=disk.percent,
                process_count=process_count
            )
            
            with self._lock:
                self.snapshots.append(snapshot)
                
                # Clean old snapshots
                cutoff_time = datetime.utcnow() - timedelta(minutes=self.history_minutes)
                self.snapshots = [s for s in self.snapshots if s.timestamp > cutoff_time]
                
        except Exception as e:
            print(f"⚠️ Failed to take system snapshot: {e}")
    
    def get_current_stats(self) -> Dict[str, Any]:
        """Get current system statistics"""
        try:
            # Current stats
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Process info
            current_process = psutil.Process()
            process_memory = current_process.memory_info()
            process_cpu = current_process.cpu_percent()
            
            return {
                'system': {
                    'cpu_percent': round(cpu_percent, 1),
                    'cpu_count': psutil.cpu_count(),
                    'memory_percent': round(memory.percent, 1),
                    'memory_total_mb': round(memory.total / (1024 * 1024)),
                    'memory_used_mb': round(memory.used / (1024 * 1024)),
                    'memory_available_mb': round(memory.available / (1024 * 1024)),
                    'disk_usage_percent': round(disk.percent, 1),
                    'process_count': len(psutil.pids())
                },
                'current_process': {
                    'pid': current_process.pid,
                    'cpu_percent': round(process_cpu, 1),
                    'memory_mb': round(process_memory.rss / (1024 * 1024), 1),
                    'memory_percent': round((process_memory.rss / memory.total) * 100, 2),
                    'threads': current_process.num_threads(),
                    'open_files': len(current_process.open_files()) if hasattr(current_process, 'open_files') else 'N/A'
                }
            }
        except Exception as e:
            return {'error': f'Failed to get system stats: {str(e)}'}
    
    def get_historical_stats(self) -> Dict[str, Any]:
        """Get historical statistics and recommendations"""
        with self._lock:
            if not self.snapshots:
                return {'error': 'No historical data available'}
            
            # Calculate averages and peaks
            cpu_values = [s.cpu_percent for s in self.snapshots]
            memory_values = [s.memory_percent for s in self.snapshots]
            memory_mb_values = [s.memory_used_mb for s in self.snapshots]
            
            stats = {
                'monitoring_duration_minutes': len(self.snapshots) * 0.5,  # Assuming 30s intervals
                'data_points': len(self.snapshots),
                'cpu': {
                    'average': round(sum(cpu_values) / len(cpu_values), 1),
                    'peak': round(max(cpu_values), 1),
                    'minimum': round(min(cpu_values), 1)
                },
                'memory': {
                    'average_percent': round(sum(memory_values) / len(memory_values), 1),
                    'peak_percent': round(max(memory_values), 1),
                    'average_mb': round(sum(memory_mb_values) / len(memory_mb_values)),
                    'peak_mb': round(max(memory_mb_values))
                }
            }
            
            # Add Render instance recommendations
            stats['render_recommendations'] = self._get_render_recommendations(stats)
            
            return stats
    
    def _get_render_recommendations(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """Generate Render instance size recommendations based on usage"""
        peak_memory_mb = stats['memory']['peak_mb']
        avg_cpu = stats['cpu']['average']
        peak_cpu = stats['cpu']['peak']
        
        recommendations = {
            'current_usage': {
                'peak_memory_mb': peak_memory_mb,
                'avg_cpu_percent': avg_cpu,
                'peak_cpu_percent': peak_cpu
            }
        }
        
        # Render instance types (approximate specs)
        instance_types = [
            {'name': 'Starter (Free)', 'ram_mb': 512, 'cpu_cores': 0.1, 'cost': '$0'},
            {'name': 'Starter', 'ram_mb': 512, 'cpu_cores': 0.5, 'cost': '$7/month'},
            {'name': 'Standard', 'ram_mb': 2048, 'cpu_cores': 1, 'cost': '$25/month'},
            {'name': 'Pro', 'ram_mb': 8192, 'cpu_cores': 2, 'cost': '$85/month'},
            {'name': 'Pro Plus', 'ram_mb': 16384, 'cpu_cores': 4, 'cost': '$185/month'},
        ]
        
        # Find suitable instances (with 30% headroom for safety)
        memory_needed = peak_memory_mb * 1.3
        suitable_instances = []
        
        for instance in instance_types:
            if instance['ram_mb'] >= memory_needed:
                suitable_instances.append({
                    **instance,
                    'memory_utilization': f"{(peak_memory_mb / instance['ram_mb'] * 100):.1f}%",
                    'headroom_mb': instance['ram_mb'] - peak_memory_mb
                })
        
        if suitable_instances:
            recommendations['suitable_instances'] = suitable_instances[:3]  # Top 3 options
            recommendations['recommended'] = suitable_instances[0]['name']
        else:
            recommendations['recommended'] = 'Custom instance needed - contact Render support'
        
        # Usage warnings
        warnings = []
        if peak_memory_mb > 400:  # 80% of starter instance
            warnings.append('Memory usage high - consider upgrading from Starter tier')
        if peak_cpu > 80:
            warnings.append('High CPU usage detected - monitor performance')
        if avg_cpu > 50:
            warnings.append('Sustained high CPU usage - consider more CPU cores')
        
        recommendations['warnings'] = warnings
        
        return recommendations

# Global monitor instance
_monitor = None

def get_system_monitor() -> SystemMonitor:
    """Get or create global system monitor instance"""
    global _monitor
    if _monitor is None:
        _monitor = SystemMonitor()
        # Auto-start monitoring in production
        if os.getenv('RENDER') or os.getenv('HEROKU'):
            _monitor.start_monitoring(interval_seconds=60)  # 1 minute intervals in production
        else:
            _monitor.start_monitoring(interval_seconds=30)  # 30 second intervals locally
    return _monitor