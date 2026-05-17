// FUN_1401145b0 @ 0x1401145b0
// purpose-guess: entity_path_register
// callers (626):
//   FUN_140001c70 @ 140001c70
//   FUN_140001d50 @ 140001d50
//   FUN_1404423d0 @ 1404423d0
//   FUN_140002020 @ 140002020
//   FUN_14000f160 @ 14000f160
//   FUN_14000f390 @ 14000f390
//   FUN_14000f420 @ 14000f420
//   FUN_14000f4b0 @ 14000f4b0
//   FUN_14000f540 @ 14000f540
//   FUN_140023430 @ 140023430
//   FUN_140023820 @ 140023820
//   FUN_140023900 @ 140023900
//   FUN_1400239e0 @ 1400239e0
//   FUN_140023ac0 @ 140023ac0
//   FUN_140023ba0 @ 140023ba0
//   FUN_140023fe0 @ 140023fe0
//   FUN_1400240c0 @ 1400240c0
//   FUN_1400241a0 @ 1400241a0
//   FUN_140024290 @ 140024290
//   FUN_140024380 @ 140024380
//   FUN_140024470 @ 140024470
//   FUN_140024560 @ 140024560
//   FUN_140024650 @ 140024650
//   FUN_140024740 @ 140024740
//   FUN_140024830 @ 140024830
//   FUN_140024920 @ 140024920
//   FUN_140024a00 @ 140024a00
//   FUN_140024ae0 @ 140024ae0
//   FUN_140024bc0 @ 140024bc0
//   FUN_140024ca0 @ 140024ca0
//   FUN_140024d90 @ 140024d90
//   FUN_140028b00 @ 140028b00
//   FUN_1400301a0 @ 1400301a0
//   FUN_140030290 @ 140030290
//   FUN_140030380 @ 140030380
//   FUN_140030470 @ 140030470
//   FUN_140030520 @ 140030520
//   FUN_1400305d0 @ 1400305d0
//   FUN_140030680 @ 140030680
//   FUN_140030730 @ 140030730
//   FUN_1400307e0 @ 1400307e0
//   FUN_1400309d0 @ 1400309d0
//   FUN_140030ab0 @ 140030ab0
//   FUN_140030b90 @ 140030b90
//   FUN_140030c70 @ 140030c70
//   FUN_140030d50 @ 140030d50
//   FUN_140030e30 @ 140030e30
//   FUN_140030f10 @ 140030f10
//   FUN_140030ff0 @ 140030ff0
//   FUN_1400310d0 @ 1400310d0


longlong * FUN_1401145b0(longlong *param_1,longlong *param_2)

{
  uint uVar1;
  longlong lVar2;
  longlong lVar3;
  undefined4 *puVar4;
  uint uVar5;
  uint uVar6;
  
  *param_1 = *param_2;
  *(uint *)(param_1 + 1) =
       *(uint *)(param_1 + 1) ^ (*(uint *)(param_1 + 1) ^ *(uint *)(param_2 + 1)) & 0x7fffffff;
  *(uint *)(param_1 + 1) =
       (*(uint *)(param_1 + 1) ^ *(uint *)(param_2 + 1)) & 0x7fffffff ^ *(uint *)(param_2 + 1);
  *(undefined4 *)((longlong)param_1 + 0xc) = 0;
  if ((int)*(uint *)(param_2 + 1) < 0) {
    return param_1;
  }
  uVar5 = *(uint *)(param_2 + 1) & 0x7fffffff;
  uVar6 = 0xf;
  if (0xf < uVar5) {
    uVar6 = uVar5;
  }
  uVar1 = uVar6 + 1;
  LOCK();
  DAT_141415474 = DAT_141415474 + 1;
  UNLOCK();
  lVar3 = _malloc_base(uVar1);
  lVar2 = *param_2;
  uVar5 = uVar5 + 1;
  if (lVar3 == 0) {
LAB_14011463a:
    puVar4 = (undefined4 *)FUN_140ca5c90();
    *puVar4 = 0x16;
  }
  else {
    if ((lVar2 != 0) && (uVar5 <= uVar1)) {
      FUN_140c96e80(lVar3,lVar2,uVar5);
      goto LAB_140114688;
    }
    FUN_140c97530(lVar3,0,uVar1);
    if (lVar2 == 0) goto LAB_14011463a;
    if (uVar5 <= uVar1) goto LAB_140114688;
    puVar4 = (undefined4 *)FUN_140ca5c90();
    *puVar4 = 0x22;
  }
  FUN_140ca5a24();
LAB_140114688:
  *param_1 = lVar3;
  *(uint *)((longlong)param_1 + 0xc) = uVar6;
  return param_1;
}

