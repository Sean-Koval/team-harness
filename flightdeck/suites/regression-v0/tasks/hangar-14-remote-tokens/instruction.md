`hangar token create|list|revoke` only work against the local database, so they do nothing useful on a laptop
pointed at a remote hangar (`HANGAR_URL` set).

When `HANGAR_URL` is set, make them use the server's API through the CLI's `_call` helper:
`create NAME` -> `POST /api/tokens` with JSON `{"name": NAME}` (print the token's id and the token itself once),
`list` -> `GET /api/tokens`, `revoke ID` -> `DELETE /api/tokens/<id>`. When `HANGAR_URL` is unset, keep the local
behaviour. Say in each command's help which mode it uses. The CLI is `src/hangar/cli.py`.
