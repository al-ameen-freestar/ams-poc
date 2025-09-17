package io.freestar.admanagement.deployments.utils;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public class PrebidModulesHelper {
    static final String[] NETWORK_SLUGS_WITH_BID_ADAPTERS = new String[]{
			"appnexus", "mediafuse"
		};

    public static Set<String> getPrebidModulesBySiteConfig() {
        return new HashSet<>(Arrays.asList(NETWORK_SLUGS_WITH_BID_ADAPTERS));
    }
}


