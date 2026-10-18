"""RPC journal contract adapter; server RPC is not yet implemented or enabled."""
import re


class CloudJournal:
    def __init__(self,rpc):
        self.rpc=rpc

    def claim(self,key,*,allowed=False):
        if allowed is not True:raise ValueError('Delivery stopped')
        if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{64}',key):
            raise ValueError('Invalid delivery identity')
        result=self.rpc('claim',{'identity':key})
        if result is None:return None
        if not isinstance(result,dict) or set(result)!={'lease'} or not isinstance(result['lease'],str) or not re.fullmatch('[a-f0-9]{64}',result['lease']):
            raise ValueError('Invalid claim response; hold without sending')
        return result['lease']

    def finish(self,key,lease,receipt=None):
        if receipt is not None and (not isinstance(receipt,str) or not 1<=len(receipt)<=200):
            raise ValueError('Invalid receipt evidence')
        if self.rpc('finish',{'identity':key,'lease':lease,'receipt':receipt}) is not True:
            raise ValueError('Delivery completion unconfirmed')

    def state(self,key):
        result=self.rpc('state',{'identity':key})
        if result is None:return None
        if (not isinstance(result,dict) or set(result)!={'state','has_receipt'}
                or result['state'] not in ('sending','uncertain','confirmed')
                or type(result['has_receipt']) is not bool):
            raise ValueError('Invalid delivery state')
        return result
