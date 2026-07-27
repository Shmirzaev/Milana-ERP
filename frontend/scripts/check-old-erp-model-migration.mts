import assert from "node:assert/strict";

import {
  paidOperationsFromDetails,
  serializePaidOperations,
  withPaidOperations,
} from "../src/lib/modelPaidOperations.ts";
import { oldErpModelInfoFromDetails } from "../src/lib/oldErpModelInfo.ts";

const explicitEmpty = paidOperationsFromDetails({ paid_operations: [] });
assert.deepEqual(explicitEmpty, []);
assert.deepEqual(serializePaidOperations(explicitEmpty), []);

const normalizedOperation = paidOperationsFromDetails({
  paid_operations: [{
    id: "legacy-op-7",
    selected: true,
    section: "sewing",
    code: "sew-007",
    name: "Chontak tikish",
    rate: 250,
    source_order: 7,
    duration: 1,
    currency: "UZB",
    stage: "Tikuv",
    control_change_direction: "sewCorrected",
    final_operation: false,
    quantity_mode: "batch",
    custom_quantity: 0,
    copies: 1,
    split_mode: "none",
    split_quantities: [],
  }],
});
assert.equal(normalizedOperation.length, 1);
assert.deepEqual(
  {
    sourceOrder: normalizedOperation[0].sourceOrder,
    duration: normalizedOperation[0].duration,
    currency: normalizedOperation[0].currency,
    sourceStage: normalizedOperation[0].sourceStage,
    changeDirection: normalizedOperation[0].changeDirection,
    finalOperation: normalizedOperation[0].finalOperation,
  },
  {
    sourceOrder: 7,
    duration: "1",
    currency: "UZB",
    sourceStage: "Tikuv",
    changeDirection: "sewCorrected",
    finalOperation: false,
  },
);
const serializedOperation = serializePaidOperations(normalizedOperation)[0];
assert.deepEqual(
  {
    sourceOrder: serializedOperation.sourceOrder,
    duration: serializedOperation.duration,
    currency: serializedOperation.currency,
    sourceStage: serializedOperation.sourceStage,
    changeDirection: serializedOperation.changeDirection,
    finalOperation: serializedOperation.finalOperation,
  },
  {
    sourceOrder: 7,
    duration: "1",
    currency: "UZB",
    sourceStage: "Tikuv",
    changeDirection: "sewCorrected",
    finalOperation: false,
  },
);

const correctionProvenance = {
  source_key: "old-erp-reviewed-correction",
  complete_sections: {
    general: {
      "35": {
        Date: "26/01/2025 11:27:54",
        "Sew Model Code": "TJ2007",
        Product: "Туника",
        Name: "4248",
        Variant: "1",
        Description: "Imported description",
        Style: "Classic",
        Company: "Milana",
        "Planning Type": "Standard",
        "Parent Sew Model": "TJ2000",
        Embroidery: false,
        "Thermal Print": true,
      },
    },
    recipes: {
      "35": [{
        source_order: 1,
        product: "Cotton fabric",
        quantity: "1.25",
        sewing_type_list: "Main",
      }],
    },
  },
};
const correctionInfo = oldErpModelInfoFromDetails({
  old_erp_migration: correctionProvenance,
});
assert.deepEqual(correctionInfo.general, {
  sourceDate: "26/01/2025 11:27:54",
  sewModelCode: "TJ2007",
  product: "Туника",
  originalName: "4248",
  modelVariant: "1",
  description: "Imported description",
  style: "Classic",
  company: "Milana",
  planningType: "Standard",
  parentSewModel: "TJ2000",
  embroidery: false,
  thermalPrint: true,
});
assert.deepEqual(correctionInfo.recipes, [{
  order: "1",
  product: "Cotton fabric",
  quantity: "1.25",
  sewingTypeList: "Main",
}]);

const deltaInfo = oldErpModelInfoFromDetails({
  old_erp_delta_migration: {
    complete_record: {
      general: {
        Date: "25/07/2026 15:27:39",
        "Sew Model Code": "FJ6020",
        Product: "Футболка женская",
        Name: "FJ6020",
        Variant: "1",
        Description: "",
        Style: "",
        Company: "",
        "Planning Type": "",
        "Parent Sew Model": "",
        Embroidery: false,
        "Thermal Print": false,
      },
      recipes: [{
        no: 2,
        product: "Rib",
        qty: 0.15,
        sewingTypeList: "Collar",
      }],
    },
  },
});
assert.equal(deltaInfo.general?.sewModelCode, "FJ6020");
assert.equal(deltaInfo.general?.modelVariant, "1");
assert.deepEqual(deltaInfo.recipes, [{
  order: "2",
  product: "Rib",
  quantity: "0.15",
  sewingTypeList: "Collar",
}]);

const roundTripped = withPaidOperations(
  {
    old_erp_migration: correctionProvenance,
    unrelated_provenance: { retained: true },
    paid_operations: [],
  },
  normalizedOperation,
);
assert.deepEqual(roundTripped.old_erp_migration, correctionProvenance);
assert.deepEqual(roundTripped.unrelated_provenance, { retained: true });
assert.deepEqual(
  {
    sourceOrder: roundTripped.paid_operations[0].sourceOrder,
    duration: roundTripped.paid_operations[0].duration,
    currency: roundTripped.paid_operations[0].currency,
    sourceStage: roundTripped.paid_operations[0].sourceStage,
    changeDirection: roundTripped.paid_operations[0].changeDirection,
    finalOperation: roundTripped.paid_operations[0].finalOperation,
  },
  {
    sourceOrder: 7,
    duration: "1",
    currency: "UZB",
    sourceStage: "Tikuv",
    changeDirection: "sewCorrected",
    finalOperation: false,
  },
);

console.log("old ERP frontend fixtures: 5/5 passed");
