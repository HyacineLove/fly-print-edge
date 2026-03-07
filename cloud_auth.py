"""
fly-print-cloud OAuth2认证客户端
实现Client Credentials流程获取access token
"""

import requests
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any


class CloudAuthClient:
    """云端OAuth2认证客户端"""
    
    def __init__(self, auth_url: str, client_id: str, client_secret: str):
        self.auth_url = auth_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = None
        
    def get_access_token(self) -> Optional[str]:
        """获取有效的access token，如果过期则自动刷新"""
        if self._is_token_valid():
            return self.access_token
        
        return self._refresh_token()
    
    def _is_token_valid(self) -> bool:
        """检查token是否有效"""
        if not self.access_token or not self.token_expires_at:
            return False
        
        # 提前5分钟刷新token
        return datetime.now() < (self.token_expires_at - timedelta(minutes=5))
    
    def _refresh_token(self) -> Optional[str]:
        """刷新access token"""
        try:
            print(f" [DEBUG] 请求OAuth2 token: {self.auth_url}")
            
            data = {
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'edge:register edge:heartbeat edge:printer edge:print edge:file'
            }
            
            # verify=False 允许自签名证书
            response = requests.post(
                self.auth_url,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                expires_in = token_data.get('expires_in', 3600)  # 默认1小时
                
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                print(f" [DEBUG] OAuth2 token获取成功，过期时间: {self.token_expires_at}")
                return self.access_token
            else:
                print(f" [DEBUG] OAuth2 token获取失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f" [DEBUG] OAuth2认证异常: {e}")
            return None
    
    def get_auth_headers(self) -> Dict[str, str]:
        """获取带认证信息的请求头"""
        token = self.get_access_token()
        if token:
            return {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
        return {'Content-Type': 'application/json'}

