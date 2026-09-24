<script setup lang="ts">
/**
 * The admin user list (spec: B-19). `require-session` runs first and `require-admin` second, so a
 * signed-out visitor goes to sign in and a member goes to the dashboard before this page renders.
 */
import { definePageMeta, useSeoMeta } from '#imports';

import { useAdminUsersQuery } from '~/composables/useAdminUsersQuery';
import styles from './index.module.scss';

defineOptions({ name: 'AdminPage' });

definePageMeta({ layout: 'protected', middleware: ['require-session', 'require-admin'] });

useSeoMeta({ description: 'Every account, for administrators.', title: 'Users' });

const { data: userPage, isError: hasFailed } = useAdminUsersQuery();

const joinedDateFormat = new Intl.DateTimeFormat('en', { dateStyle: 'medium' });

/** Format a join timestamp for the table. */
function formatJoinedDate(createdAt: string): string {
    return joinedDateFormat.format(new Date(createdAt));
}
</script>

<template>
    <section data-test-id="admin-page">
        <h1>Users</h1>
        <p v-if="hasFailed" role="alert">The user list could not be loaded.</p>
        <template v-else-if="userPage">
            <table :class="styles.table">
                <thead>
                    <tr>
                        <th scope="col">Email</th>
                        <th scope="col">Role</th>
                        <th scope="col">Joined</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="listedUser in userPage.data" :key="listedUser.id">
                        <td>{{ listedUser.email }}</td>
                        <td>{{ listedUser.role }}</td>
                        <td>{{ formatJoinedDate(listedUser.created_at) }}</td>
                    </tr>
                </tbody>
            </table>
            <p>Showing {{ userPage.data.length }} of {{ userPage.meta.total }}</p>
        </template>
    </section>
</template>
