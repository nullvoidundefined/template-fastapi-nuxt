/**
 * Resolves the client's address from the proxy chain (spec: Architecture, "Client IP trust chain").
 *
 * Railway's edge appends the connecting client's address as the last `X-Forwarded-For` entry;
 * every earlier entry is supplied by the client and never trusted. Only that last entry is used,
 * and only when it is a bare IPv4 or IPv6 address, so a port, a bracketed form, or anything that
 * could smuggle another header is rejected. Without a usable entry the socket's peer address is
 * used, which is the browser itself when no edge sits in front (local development). The app's
 * server-side API client and the Nitro proxy share this one implementation of the trust rule.
 */

const ipv4Pattern = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
const ipv6GroupPattern = /^[0-9a-f]{1,4}$/i;
const ipv6GroupCount = 8;

/** Return the trusted client address, or undefined when neither source is a valid address. */
export function resolveClientAddress(
    forwardedFor: string | null | undefined,
    socketAddress?: string,
): string | undefined {
    const edgeAddress = forwardedFor?.split(',').at(-1)?.trim();
    if (edgeAddress && isIpAddress(edgeAddress)) {
        return edgeAddress;
    }
    if (socketAddress && isIpAddress(socketAddress)) {
        return socketAddress;
    }
    return undefined;
}

/** Return true for a bare IPv4 or IPv6 address, with no port, brackets, or zone. */
function isIpAddress(candidate: string): boolean {
    return ipv4Pattern.test(candidate) || isIpv6Address(candidate);
}

/** Return true for an IPv6 address, allowing one `::` and a trailing embedded IPv4 address. */
function isIpv6Address(candidate: string): boolean {
    const halves = candidate.split('::');
    if (halves.length > 2) {
        return false;
    }
    const groups = halves.flatMap((half) => (half === '' ? [] : half.split(':')));
    const lastGroup = groups.at(-1) ?? '';
    const embedsIpv4 = lastGroup.includes('.');
    if (embedsIpv4 && !ipv4Pattern.test(lastGroup)) {
        return false;
    }
    const hexGroups = embedsIpv4 ? groups.slice(0, -1) : groups;
    if (!hexGroups.every((group) => ipv6GroupPattern.test(group))) {
        return false;
    }
    const groupCount = hexGroups.length + (embedsIpv4 ? 2 : 0);
    return halves.length === 2 ? groupCount < ipv6GroupCount : groupCount === ipv6GroupCount;
}
