import json
import platform
import subprocess
import importlib.util
import psutil
import torch


def hardware():
    result = {'windows': platform.platform(), 'cpu': platform.processor(),
              'ram_gib': round(psutil.virtual_memory().total / 2**30, 2),
              'torch': torch.__version__, 'cuda': torch.cuda.is_available(), 'cuda_build': torch.version.cuda,
              'onnxruntime_installed': bool(importlib.util.find_spec('onnxruntime'))}
    if result['cuda']:
        result['gpu'] = torch.cuda.get_device_name()
        free, total = torch.cuda.mem_get_info()
        result.update(vram_total_gib=round(total/2**30, 2), vram_free_gib=round(free/2**30, 2))
    else:
        try:
            flags = subprocess.CREATE_NO_WINDOW if platform.system() == 'Windows' else 0
            value = subprocess.run(['powershell', '-NoProfile', '-Command',
                "[ordered]@{cpu=(Get-CimInstance Win32_Processor).Name; adapters=@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion)} | ConvertTo-Json -Compress -Depth 4"],
                capture_output=True, text=True, timeout=15, creationflags=flags)
            devices = json.loads(value.stdout)
            result['cpu'] = devices['cpu']
            result['display_adapters'] = devices['adapters']
        except Exception as error:
            result['display_query_error'] = str(error)
    return result
