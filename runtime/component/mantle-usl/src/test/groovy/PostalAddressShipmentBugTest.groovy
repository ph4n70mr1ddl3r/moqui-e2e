/*
 * This software is in the public domain under CC0 1.0 Universal plus a
 * Grant of Patent License.
 *
 * To the extent possible under law, the author(s) have dedicated all
 * copyright and related and neighboring rights to this software to the
 * public domain worldwide. This software is distributed without any
 * warranty.
 *
 * You should have received a copy of the CC0 Public Domain Dedication
 * along with this software (see the LICENSE.md file). If not, see
 * <http://creativecommons.org/publicdomain/zero/1.0/>.
 */

import org.moqui.Moqui
import org.moqui.context.ExecutionContext
import org.slf4j.Logger
import org.slf4j.LoggerFactory
import spock.lang.Shared
import spock.lang.Specification

/**
 * Test for a bug in ContactServices.create#PostalAddress where the shipmentSetDest condition
 * has incorrect operator precedence due to missing parentheses, causing the destination postal
 * address to be set on a shipment route segment even when shipmentSetDest is not specified.
 *
 * Bug location: runtime/component/mantle-usl/service/mantle/party/ContactServices.xml
 * In the create#PostalAddress service, the shipmentSetDest condition is:
 *   shipmentSetDest && routeSegment.destPostalContactMechId == null ||
 *       (routeSegment.shipmentRouteSegmentSeqId == shipmentRouteSegmentSeqId)
 * which evaluates as:
 *   (shipmentSetDest && routeSegment.destPostalContactMechId == null) ||
 *       (routeSegment.shipmentRouteSegmentSeqId == shipmentRouteSegmentSeqId)
 * The correct condition should be:
 *   shipmentSetDest && (routeSegment.destPostalContactMechId == null ||
 *       routeSegment.shipmentRouteSegmentSeqId == shipmentRouteSegmentSeqId)
 */
class PostalAddressShipmentBugTest extends Specification {
    @Shared
    protected final static Logger logger = LoggerFactory.getLogger(PostalAddressShipmentBugTest.class)
    @Shared
    ExecutionContext ec

    def setupSpec() {
        ec = Moqui.getExecutionContext()
        ec.user.loginUser("admin", "admin")

        ec.entity.tempSetSequencedIdPrimary("mantle.shipment.Shipment", 99100, 10)
        ec.entity.tempSetSequencedIdPrimary("mantle.shipment.ShipmentRouteSegment", 99100, 10)
        ec.entity.tempSetSequencedIdPrimary("mantle.shipment.ShipmentItem", 99100, 10)
        ec.entity.tempSetSequencedIdPrimary("mantle.shipment.ShipmentItemSource", 99100, 10)
        ec.entity.tempSetSequencedIdPrimary("mantle.party.contact.ContactMech", 99100, 10)
    }

    def cleanupSpec() {
        ec.entity.tempResetSequencedIdPrimary("mantle.shipment.Shipment")
        ec.entity.tempResetSequencedIdPrimary("mantle.shipment.ShipmentRouteSegment")
        ec.entity.tempResetSequencedIdPrimary("mantle.shipment.ShipmentItem")
        ec.entity.tempResetSequencedIdPrimary("mantle.shipment.ShipmentItemSource")
        ec.entity.tempResetSequencedIdPrimary("mantle.party.contact.ContactMech")

        ec.destroy()
    }

    def setup() {
        ec.artifactExecution.disableAuthz()
    }

    def cleanup() {
        ec.artifactExecution.enableAuthz()
    }

    def "create postal address for shipment - shipmentSetOrigin only should NOT set destPostalContactMechId"() {
        when:
        // Create a shipment with a route segment
        Map shipmentOut = ec.service.sync().name("create#mantle.shipment.Shipment")
                .parameters([shipmentTypeEnumId: 'ShpTpSales',
                             fromPartyId: 'ORG_ZIZI_RETAIL', toPartyId: 'CustJqp',
                             statusId: 'ShipInput']).call()

        String shipmentId = shipmentOut.shipmentId

        // Create a route segment for the shipment
        Map rsOut = ec.service.sync().name("create#mantle.shipment.ShipmentRouteSegment")
                .parameters([shipmentId: shipmentId,
                             shipmentRouteSegmentSeqId: '00001']).call()

        // Verify that both origin and dest are null before the test
        def routeSegmentBefore = ec.entity.find("mantle.shipment.ShipmentRouteSegment")
                .condition("shipmentId", shipmentId)
                .condition("shipmentRouteSegmentSeqId", "00001").one()

        then:
        routeSegmentBefore != null
        routeSegmentBefore.originPostalContactMechId == null
        routeSegmentBefore.destPostalContactMechId == null

        when:
        // Create a postal address with ONLY shipmentSetOrigin=true
        // This should set originPostalContactMechId but NOT destPostalContactMechId
        Map paOut = ec.service.sync().name("mantle.party.ContactServices.create#PostalAddress")
                .parameters([address1: '123 Origin St',
                             city: 'OriginCity',
                             stateProvinceGeoId: 'USA_UT',
                             postalCode: '84001',
                             countryGeoId: 'USA',
                             shipmentId: shipmentId,
                             shipmentRouteSegmentSeqId: '00001',
                             shipmentSetOrigin: true]).call()

        // Fetch the route segment after
        def routeSegmentAfter = ec.entity.find("mantle.shipment.ShipmentRouteSegment")
                .condition("shipmentId", shipmentId)
                .condition("shipmentRouteSegmentSeqId", "00001").one()

        then:
        // Origin should be set
        routeSegmentAfter.originPostalContactMechId != null
        routeSegmentAfter.originPostalContactMechId == paOut.contactMechId

        // BUG: Dest should NOT be set - only shipmentSetOrigin was specified
        // With the bug, destPostalContactMechId will also be set because the condition
        // evaluates as: (shipmentSetDest && dest == null) || (seqId == seqId)
        // Since seqId matches, the condition is true even though shipmentSetDest is not specified
        routeSegmentAfter.destPostalContactMechId == null

        cleanup:
        // Clean up
        if (shipmentId) {
            ec.service.sync().name("delete#mantle.shipment.ShipmentRouteSegment")
                    .parameters([shipmentId: shipmentId, shipmentRouteSegmentSeqId: '00001']).call()
            ec.service.sync().name("delete#mantle.shipment.Shipment")
                    .parameters([shipmentId: shipmentId]).call()
        }
    }

    def "create postal address for shipment - shipmentSetDest=true should set destPostalContactMechId"() {
        when:
        // Create a shipment with a route segment
        Map shipmentOut = ec.service.sync().name("create#mantle.shipment.Shipment")
                .parameters([shipmentTypeEnumId: 'ShpTpSales',
                             fromPartyId: 'ORG_ZIZI_RETAIL', toPartyId: 'CustJqp',
                             statusId: 'ShipInput']).call()

        String shipmentId = shipmentOut.shipmentId

        // Create a route segment for the shipment
        ec.service.sync().name("create#mantle.shipment.ShipmentRouteSegment")
                .parameters([shipmentId: shipmentId,
                             shipmentRouteSegmentSeqId: '00001']).call()

        // Create a postal address with shipmentSetDest=true
        Map paOut = ec.service.sync().name("mantle.party.ContactServices.create#PostalAddress")
                .parameters([address1: '456 Dest St',
                             city: 'DestCity',
                             stateProvinceGeoId: 'USA_CA',
                             postalCode: '90210',
                             countryGeoId: 'USA',
                             shipmentId: shipmentId,
                             shipmentRouteSegmentSeqId: '00001',
                             shipmentSetDest: true]).call()

        // Fetch the route segment after
        def routeSegmentAfter = ec.entity.find("mantle.shipment.ShipmentRouteSegment")
                .condition("shipmentId", shipmentId)
                .condition("shipmentRouteSegmentSeqId", "00001").one()

        then:
        // Dest should be set
        routeSegmentAfter.destPostalContactMechId != null
        routeSegmentAfter.destPostalContactMechId == paOut.contactMechId

        // Origin should NOT be set (only shipmentSetDest was specified)
        routeSegmentAfter.originPostalContactMechId == null

        cleanup:
        if (shipmentId) {
            ec.service.sync().name("delete#mantle.shipment.ShipmentRouteSegment")
                    .parameters([shipmentId: shipmentId, shipmentRouteSegmentSeqId: '00001']).call()
            ec.service.sync().name("delete#mantle.shipment.Shipment")
                    .parameters([shipmentId: shipmentId]).call()
        }
    }
}
