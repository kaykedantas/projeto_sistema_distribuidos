from typing import List, Dict, Optional

def elect_master(replies: List[Dict]) -> Optional[Dict]:
    if not replies:
        return None
    sorted_replies = sorted(replies, key=lambda r: (r.get('MASTER_NAME',''), r.get('MASTER_IP','')))
    return sorted_replies[0]
