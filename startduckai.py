import aiohttp
import requests

VERSION = '0.1'

#
#  StartDuck AI API v1.2
# 

DEFAULT_API_URL: str = 'https://bigduck.ai'
DEFAULT_API_TIMEOUT: float = 240.0

class MessageType:
    TEXT     = 'text'
    VOICE    = 'voice'
    IMAGE    = 'image'
    STICKER  = 'sticker'
    AUDIO    = 'audio'
    VIDEO    = 'video'
    DOCUMENT = 'document'
    
class MessageRole:
    USER      = 'user'
    ASSISTANT = 'assistant'
    
MIME_TYPES = {
    'image/bmp'          : ('.bmp',),
    'image/png'          : ('.png',),
    'image/jpeg'         : ('.jpg', '.jpeg',),
    'image/gif'          : ('.gif',),
    'image/webp'         : ('.webp',),

    'sticker/lottie'     : (),

    'video/mp4'          : ('.mp4',),
    'video/webm'         : ('.webm',),

    'audio/wav'          : ('.wav',),
    'audio/mpeg'         : ('.mp3',),
    'audio/mp4'          : ('.m4a', '.mp4',),
    'audio/ogg'          : ('.ogg',),

    'text/plain'         : ('.txt',),
    'application/pdf'    : ('.pdf',),
    'application/msword' : ('.doc',),
    'application/mswordx': ('.docx',),
    'application/ppt'    : ('.ppt',),
    'application/pptx'   : ('.pptx',)
}

#
#  Message structs
#
        
class StoredMessage:
    def __init__(self, role: str[MessageRole], text: str):
        self.role = role
        self.text = text
        
    def serialize(self) -> dict:
        return {
            'role': self.role,
            'text': self.text
        }
        
    @staticmethod
    def deserialize(packed: dict) -> 'StoredMessage':
        return StoredMessage(
            packed['role'], 
            packed['text']
        )
        
class MessageBase:
    '''
        A message struct.
    '''
    type = None
    mime = []
    
    def __init__(self, data: str, mime: str[MessageType]):
        '''
            data - A message text or url to your media content.
            mime - A mimetype of your content.
        '''
        self.data = data
        self.mime = mime
        
        if not mime.lower() in self.mimetypes:
            raise InvalidMimeType('Bad message content mimetype.')
        
    def serialize(self) -> dict:
        return {
            'type': self.type,
            'mime': self.mime,
            'data': self.data
        }
        
class TextMessage(MessageBase):
    type = MessageType.TEXT
    mime = ['text/plain']
    
    def __init__(self, text: str):
        super().__init__(text, self.mime[0])
        
class VoiceMessage(MessageBase):
    type = MessageType.VOICE
    mime = ['audio/wav', 'audio/mpeg', 'audio/mp4', 'audio/ogg']
        
class ImageMessage(MessageBase):
    type = MessageType.IMAGE
    mime = ['image/bmp', 'image/png', 'image/jpeg', 'image/gif', 'image/webp']
        
class StickerMessage(MessageBase):
    type = MessageType.STICKER
    mime = ['image/bmp', 'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'sticker/lottie']
    
class AudioMessage(MessageBase):
    type = MessageType.AUDIO
    mime = ['audio/wav', 'audio/mpeg', 'audio/mp4', 'audio/ogg']
    
class VideoMessage(MessageBase):
    type = MessageType.VIDEO
    mime = ['video/mp4', 'video/webm']
    
class DocumentMessage(MessageBase):
    type = MessageType.DOCUMENT
    mime = ['text/plain', 'application/pdf', 'application/msword', 'application/mswordx', 'application/ppt', 'application/pptx']
    
#
#  Reply struct
#

class ReplyMessage:
    def __init__(
        self,
        text            : str,
        text_markdown   : str,
        text_markdown_v2: str,
        chatbot_uuid    : str,
        client_id       : str,
        metadata        : dict = None
    ):
        self.text             = text
        self.text_markdown    = text_markdown
        self.text_markdown_v2 = text_markdown_v2
        self.chatbot_uuid     = chatbot_uuid
        self.client_id        = client_id
        self.metadata         = metadata
        
    @staticmethod
    def deserialize(packed: dict) -> 'ReplyMessage':
        return ReplyMessage(
            packed['answer']['text'],
            packed['answer']['fbmd'],
            packed['answer']['mdv2'],
            packed['chatbot_uuid'], 
            packed['client_id'], 
            packed.get('metadata', None)
        )
    
#
#  Sync API
#

class SyncAPI:
    def __init__(
        self,
        api_key     : str = None,
        chatbot_uuid: str = None,
        webhook     : str = None,
        api_url     : str = DEFAULT_API_URL,
        timeout     : float = DEFAULT_API_TIMEOUT
    ):
        '''
            StartDuckAI API initialization.
            
            api_key      - API key from your account.
            chatbot_uuid - UUID of dest chatbot.
            webhook      - Your webhook for receive reply's (Must handle HTTP POST requests!).
            api_url      - In case you need a non-main API server.  
            timeout      - HTTP requests timeout, default is 240 seconds.
        '''
        self.api_url      = api_url
        self.api_key      = api_key
        self.webhook      = webhook
        self.chatbot_uuid = chatbot_uuid
        self.timeout      = timeout


    def _check_for_errors(self, answer: dict) -> None:
        match answer['status']:
            case 'success':
                return

            case 'error':
                match answer['error']:
                    case 'no_reply':
                        raise NoReply(answer['message'])

                    case 'in_process':
                        raise InProcess(answer['message'])

                    case 'chatbot_not_active':
                        raise ChatBotNotActive(answer['message'])

                    case 'chatbot_not_found':
                        raise ChatBotNotFound(answer['message'])

                    case 'chatbot_not_trained':
                        raise ChatBotNotTrained(answer['message'])

                    case 'bad_request':
                        raise BadRequest(f"Perhaps the `startduckai` package is outdated. Error message: {answer['message']}")

                    case 'access_denied':
                        raise AccessDenied(answer['message'])

                    case 'rpd_limit_reached':
                        raise RPDLimitReached(answer['message'])

                    case 'spam_block':
                        raise SpamBlock(answer['message'])

                    case _:
                        raise UnknownError('The API returned an unexpected status code.')

            case _:
                raise UnknownError('The API returned an unexpected status code.')


    def send_messages(
        self,
        client_id: str,
        messages : list[TextMessage | VoiceMessage | ImageMessage | StickerMessage | AudioMessage | VideoMessage | DocumentMessage],
        metadata : dict = None,
        via_crm  : bool = False
    ) -> None:
        '''
            Sends your messages.
            
            client_id - Any UUID of client (must be unique for each client/user).
            messages  - List of messages.
            metadata  - Any data which you can put here - it will be returned to your webhook without changes. May be null.
            via_crm   - If True - the message processing pipeline will be built through our CRM.
        '''
        
        if len(messages) == 0:
            raise BadRequest('List of messages must contain at least one message!')
        
        resp = requests.post(
            url = f'{self.api_url}/integrations{'/crm' if via_crm else ''}/webhook',
            timeout = self.timeout,
            json = {
                'api_key'     : self.api_key,
                'chatbot_uuid': self.chatbot_uuid,
                'client_id'   : client_id,
                'messages'    : [ m.serialize() for m in messages ],
                'webhook'     : self.webhook,
                'metadata'    : metadata if metadata != None else {}
            }
        )
        
        if resp.status_code != 200:
            raise UnknownError('The API returned an unexpected status code.')
        
        self._check_for_errors(resp.json())
        
    def __enter__(self) -> 'SyncAPI':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return exc_val is None
    
    
    def parse_reply(self, response_json: dict) -> ReplyMessage:
        '''
            This method parses json data from your webhook.
            
            response_json - json data from request.
        '''
        try:
            return ReplyMessage.deserialize(response_json)
        except KeyError as E:
            raise BadResponse('The API returned an unexpected response. Perhaps the `startduckai` package is outdated.') 
        
        
#
#  Async API
#

class AsyncAPI(SyncAPI):
    async def send_messages(
        self,
        client_id: str,
        messages : list[TextMessage | VoiceMessage | ImageMessage | StickerMessage | AudioMessage | VideoMessage | DocumentMessage],
        metadata : dict = None,
        via_crm  : bool = False
    ) -> None:
        '''
            Sends your messages.
            
            client_id - Any UUID of client (must be unique for each client/user).
            messages  - List of messages.
            metadata  - Any data which you can put here - it will be returned to your webhook without changes. May be null.
            via_crm   - If True - the message processing pipeline will be built through our CRM.
        '''
        
        async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(self.timeout)) as session:
            async with session.post(
                url = f'{self.api_url}/integrations{'/crm' if via_crm else ''}/webhook',
                json = {
                    'api_key'     : self.api_key,
                    'chatbot_uuid': self.chatbot_uuid,
                    'client_id'   : client_id,
                    'messages'    : [ m.serialize() for m in messages ],
                    'webhook'     : self.webhook,
                    'metadata'    : metadata if metadata != None else {}
                }
            ) as resp:
                if resp.status != 200:
                    raise UnknownError('The API returned an unexpected status code.')
        
                self._check_for_errors(await resp.json())
                
    async def __aenter__(self) -> 'AsyncAPI':
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return exc_val is None


#
#  Possible exceptions
#

class InvalidMimeType(Exception):
    pass

class TooManyAttemptsReturnError(Exception):
    pass

class MessageInQueue(Exception):
    pass

class NoReply(Exception):
    pass

class InProcess(Exception):
    pass

class MessageSizeLimit(Exception):
    pass

class ChatBotNotActive(Exception):
    pass

class ChatBotNotFound(Exception):
    pass

class ChatBotNotTrained(Exception):
    pass

class BadRequest(Exception):
    pass

class BadResponse(Exception):
    pass

class AccessDenied(Exception):
    pass

class RPDLimitReached(Exception):
    pass

class SpamBlock(Exception):
    pass

class UnknownError(Exception):
    pass