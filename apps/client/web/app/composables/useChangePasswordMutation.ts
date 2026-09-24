/**
 * Changes the signed-in user's password (spec: B-13, B-50). The session entry is left alone: the
 * backend keeps the caller's own session, so who is signed in has not changed.
 */
import { useMutation } from '@tanstack/vue-query';

import { changePassword } from '~/api/changePassword';
import { useApiClient } from '~/composables/useApiClient';
import type { CurrentUser } from '~/types/currentUser';
import type { PasswordChangeInput } from '~/types/passwordChangeInput';

/** Return the mutation the profile form submits through. */
export function useChangePasswordMutation(): ReturnType<
    typeof useMutation<CurrentUser, Error, PasswordChangeInput>
> {
    const apiClient = useApiClient();
    return useMutation<CurrentUser, Error, PasswordChangeInput>({
        mutationFn: (passwordChange) => changePassword(apiClient, passwordChange),
    });
}
