/** The signed-in user as every surface reads it: what the backend returns from `GET /v1/auth/me`. */
export type CurrentUser = {
    email: string;
    id: string;
};
