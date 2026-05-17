// FUN_14048eef0 @ 0x14048eef0
// purpose-guess: register_file_extension
// callers (30):
//   FUN_1403090e0 @ 1403090e0
//   FUN_140309ab0 @ 140309ab0
//   FUN_140309c10 @ 140309c10
//   FUN_140309de0 @ 140309de0
//   FUN_14030a190 @ 14030a190
//   FUN_14030af10 @ 14030af10
//   FUN_140314350 @ 140314350
//   FUN_140318c50 @ 140318c50
//   FUN_140318fe0 @ 140318fe0
//   FUN_14031a040 @ 14031a040
//   FUN_14031a210 @ 14031a210
//   FUN_14031aab0 @ 14031aab0
//   FUN_14031b320 @ 14031b320
//   FUN_14031bd40 @ 14031bd40
//   FUN_14031c250 @ 14031c250
//   FUN_14031ca20 @ 14031ca20
//   FUN_1404663a0 @ 1404663a0
//   FUN_14047be40 @ 14047be40
//   FUN_14047c300 @ 14047c300
//   FUN_14048e0b0 @ 14048e0b0
//   FUN_1405cb220 @ 1405cb220
//   FUN_1405cbf40 @ 1405cbf40
//   FUN_140635dd0 @ 140635dd0
//   FUN_14063b540 @ 14063b540
//   FUN_140671450 @ 140671450
//   FUN_1406c6550 @ 1406c6550
//   FUN_1406cd990 @ 1406cd990
//   FUN_14086b5f0 @ 14086b5f0
//   FUN_140a26cc0 @ 140a26cc0
//   FUN_140a27b80 @ 140a27b80


void FUN_14048eef0(longlong param_1,undefined8 param_2)

{
  longlong *plVar1;
  undefined8 uVar2;
  undefined8 *puVar3;
  longlong lVar4;
  ulonglong uVar5;
  uint uVar6;
  uint uVar7;
  longlong local_18;
  uint local_10;
  int local_c;
  
  if (*(uint *)(param_1 + 0x38) != 0) {
    plVar1 = *(longlong **)(param_1 + 0x30);
    uVar5 = 0;
    do {
      lVar4 = *plVar1;
      if (*(int *)(lVar4 + 8) == 0x442a26) {
        uVar5 = 0;
        if (lVar4 != 0) {
          uVar5 = lVar4 + 0x10;
        }
        if (uVar5 != 0) {
          uVar7 = *(uint *)(uVar5 + 8) & 0x7fffffff;
          uVar6 = uVar7 + 1;
          lVar4 = FUN_140510c20(uVar5,(ulonglong)uVar6);
          *(undefined1 *)((ulonglong)uVar7 + lVar4) = 0x3b;
          *(undefined1 *)((ulonglong)uVar6 + lVar4) = 0;
          *(uint *)(uVar5 + 8) = *(uint *)(uVar5 + 8) & 0x80000000;
          *(uint *)(uVar5 + 8) = *(uint *)(uVar5 + 8) | uVar6 & 0x7fffffff;
          FUN_140510ed0(uVar5,param_2);
          return;
        }
        break;
      }
      uVar7 = (int)uVar5 + 1;
      uVar5 = (ulonglong)uVar7;
      plVar1 = plVar1 + 1;
    } while (uVar7 < *(uint *)(param_1 + 0x38));
  }
  FUN_1401145b0(&local_18,param_2);
  uVar2 = FUN_140493450();
  puVar3 = (undefined8 *)FUN_140215b10(param_1 + 0x30,*(undefined4 *)(param_1 + 0x38));
  *puVar3 = uVar2;
  if (((local_c != 0) && ((local_10 & 0x80000000) == 0)) && (local_18 != 0)) {
    LOCK();
    DAT_14143ea74 = DAT_14143ea74 + 1;
    UNLOCK();
    thunk_FUN_140cbe5f0();
  }
  return;
}

