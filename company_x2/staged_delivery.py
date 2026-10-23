"""Internal staged adapter contract; no production browser implementation."""
import hashlib


class StagedAdapter:
    """Backend staging must be reversible and must not submit or upload data.

    The operator supplies the backend; page text must never select one.
    Backend commit performs the single irreversible action.
    """
    def __init__(self,backend):
        self.backend=backend

    def send_checked(self,destination,artifact,authorize):
        staged=self.backend.stage(destination,artifact)
        if (not isinstance(staged,dict) or staged.get('destination')!=destination
                or staged.get('artifact_sha256')!=hashlib.sha256(artifact).hexdigest()):
            raise ValueError('Staged destination or artifact changed')
        # A live check after navigation/file selection, immediately before commit.
        if authorize() is not True:raise ValueError('Delivery stopped after staging')
        return self.backend.commit(staged)
