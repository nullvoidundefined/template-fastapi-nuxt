// @vitest-environment node
/**
 * Unit tests for the edge-appended address (spec: Architecture, "Client IP trust chain").
 * Only the final forwarded entry is trusted; malformed entries fall back to a valid peer.
 */
import { describe, it, expect } from 'vitest';

describe('resolveClientAddress', () => {
    it.each([
        ['a single address', '203.0.113.7', undefined, '203.0.113.7'],
        ['spoofed earlier addresses', '1.1.1.1, 2.2.2.2, 203.0.113.7', undefined, '203.0.113.7'],
        ['surrounding whitespace', '1.1.1.1,  203.0.113.7  ', undefined, '203.0.113.7'],
        ['an IPv6 final address', '1.1.1.1, 2001:db8::7', undefined, '2001:db8::7'],
        ['an invalid final entry', '203.0.113.7, not-an-ip', '192.0.2.9', '192.0.2.9'],
        ['an absent header', undefined, '192.0.2.9', '192.0.2.9'],
        ['a null header', null, '2001:db8::9', '2001:db8::9'],
        ['an empty header', '', '192.0.2.9', '192.0.2.9'],
        ['a trailing empty entry', '203.0.113.7, ', '192.0.2.9', '192.0.2.9'],
        ['no addresses', undefined, undefined, undefined],
        ['two invalid sources', 'not-an-ip', 'invalid-peer', undefined],
        ['an invalid socket address alone', undefined, '999.1.1.1', undefined],
        ['an out-of-range IPv4 entry', '203.0.113.999', undefined, undefined],
        ['an IPv4 address with a port', '203.0.113.7:443', undefined, undefined],
        ['a bracketed IPv6 address with a port', '[2001:db8::7]:443', undefined, undefined],
        ['a header injection attempt', '203.0.113.7\r\nX-Evil: 1', undefined, undefined],
    ])(
        'Client IP trust chain: resolves %s',
        async (_case, forwardedFor, socketAddress, expected) => {
            const { resolveClientAddress } =
                await import('../../../../shared/services/resolveClientAddress');

            expect(resolveClientAddress(forwardedFor, socketAddress)).toBe(expected);
        },
    );
});
